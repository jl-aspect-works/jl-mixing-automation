"""Authoritative cross-platform revision creation service."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .context import resolve_project, studio_root as resolve_studio_root
from .errors import ContextError, UnsafeOperationError, ValidationError
from .metadata import now_iso8601, validate_v11
from .paths import assert_no_case_insensitive_child_collision, assert_no_symlink_components
from .revision_source import RevisionSourcePlan, build_plan, copy_from_plan
from .transactions import _fail_requested, _injected_failure, create_staging_directory, create_staging_file
from .versions import application_root


@dataclass(frozen=True)
class RevisionCreateRequest:
    project_root: Path
    description: str | None = None
    source: Path | None = None
    change_directory: bool | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class RevisionCreateResult:
    project_root: Path
    revision_root: Path
    number: int
    description: str
    previous_revision: int
    manifest: dict[str, Any]
    effective_cd: bool
    source_plan: RevisionSourcePlan | None
    created: bool


def _load_manifest(project_root: Path) -> dict[str, Any]:
    manifest_path = project_root / "00_Admin" / "project-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ContextError(f"Project manifest not found or unsafe: {manifest_path}")
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid project manifest: {manifest_path}") from exc
    validate_v11(document.get("metadata"), "mixing-project", mutability="mutable")
    return document


def _revision_lifecycle(record: dict[str, Any]) -> str:
    lifecycle = record.get("lifecycle", "open")
    if lifecycle not in {"open", "closed"}:
        raise ValidationError(f"Revision {record.get('number')} has invalid lifecycle state: {lifecycle}")
    return lifecycle


def _validate_project_state(document: dict[str, Any]) -> int:
    state = document.get("state")
    revisions = document.get("revisions")
    if not isinstance(state, dict) or not isinstance(revisions, list):
        raise ValidationError("Project manifest has invalid revision state.")
    current = state.get("current_revision")
    if not isinstance(current, int) or isinstance(current, bool) or current < 0:
        raise ValidationError("Project state.current_revision must be a non-negative integer.")

    numbers: list[int] = []
    open_numbers: list[int] = []
    revision_ids: set[str] = set()
    for record in revisions:
        if not isinstance(record, dict) or not isinstance(record.get("number"), int):
            raise ValidationError("Project manifest contains an invalid revision record.")
        number = record["number"]
        revision_id = record.get("revision_id")
        if number < 1 or not isinstance(revision_id, str) or not revision_id:
            raise ValidationError("Project manifest contains an invalid revision record.")
        if revision_id in revision_ids:
            raise ValidationError("Project manifest contains duplicate revision IDs.")
        revision_ids.add(revision_id)
        numbers.append(number)
        if _revision_lifecycle(record) == "open":
            open_numbers.append(number)

    if numbers != list(range(1, len(numbers) + 1)):
        raise ValidationError("Project revision records must use contiguous immutable revision numbers.")
    expected_current = max(open_numbers, default=0)
    if current != expected_current:
        raise ValidationError(
            f"Project state.current_revision must equal the highest open revision ({expected_current})."
        )
    if not revisions and (state.get("approved_revision") is not None or state.get("delivered_revision") is not None):
        raise ValidationError("Project without revision history cannot have approval or delivery pointers.")
    for pointer_name in ("approved_revision", "delivered_revision"):
        pointer = state.get(pointer_name)
        if pointer is not None and (not isinstance(pointer, int) or isinstance(pointer, bool) or pointer not in numbers):
            raise ValidationError(f"Project state.{pointer_name} is invalid.")
    return current


def _validate_schema(document: dict[str, Any]) -> None:
    schema_path = application_root() / "schemas" / "project-manifest.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextError(f"Project schema not found or invalid: {schema_path}") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda error: list(error.path))
    if errors:
        raise ValidationError(f"Generated project manifest failed schema validation: {errors[0].message}")


def _load_studio_cd(project_root: Path) -> bool:
    studio_root = resolve_studio_root(project_root)
    studio_path = studio_root / "Studio" / "studio.json"
    try:
        studio = json.loads(studio_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid studio configuration: {studio_path}") from exc
    cli = studio.get("cli") if isinstance(studio.get("cli"), dict) else {}
    return cli.get("change_directory_after_create") is True


def _render_notes(number: int, description: str) -> str:
    template_path = application_root() / "templates" / "Revision_Notes.md"
    try:
        text = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContextError(f"Required template not found: {template_path}") from exc
    return text.replace("{{REVISION_NUMBER}}", str(number)).replace("{{REVISION_DESCRIPTION}}", description)


def _restore_manifest(path: Path, data: bytes, mode: int) -> None:
    fd, restore = create_staging_file(path.parent, f".{path.name}.jl-restore-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(restore, mode)
        os.replace(restore, path)
    finally:
        if restore.exists():
            restore.unlink()


def create_revision(request: RevisionCreateRequest) -> RevisionCreateResult:
    project_root = resolve_project(request.project_root, Path.cwd())
    studio_root = resolve_studio_root(project_root)
    assert_no_symlink_components(studio_root, project_root)
    manifest_path = project_root / "00_Admin" / "project-manifest.json"
    revisions_root = project_root / "04_Revisions"
    if revisions_root.is_symlink() or not revisions_root.is_dir():
        raise ContextError(f"Revision root is missing or unsafe: {revisions_root}")
    assert_no_symlink_components(project_root, revisions_root)

    manifest = _load_manifest(project_root)
    previous_revision = _validate_project_state(manifest)
    historical_numbers = [
        record.get("number") for record in manifest.get("revisions", [])
        if isinstance(record, dict) and isinstance(record.get("number"), int)
    ]
    number = max(historical_numbers, default=0) + 1
    if request.description is None:
        description = "Initial mix" if number == 1 else f"Revision {number}"
    else:
        description = request.description.strip()
        if not description:
            raise ValidationError("revision description must not be empty.")

    revision_name = f"Revision_{number:02d}"
    assert_no_case_insensitive_child_collision(revisions_root, revision_name)
    revision_root = revisions_root / revision_name
    if revision_root.exists() or revision_root.is_symlink():
        raise UnsafeOperationError(f"Revision destination already exists: {revision_root}")

    source_plan = build_plan(request.source) if request.source is not None else None
    inherited_cd = _load_studio_cd(project_root)
    effective_cd = request.change_directory if request.change_directory is not None else inherited_cd

    timestamp = now_iso8601()
    revision_id = str(uuid.uuid4())
    existing_ids = {record.get("revision_id") for record in manifest.get("revisions", []) if isinstance(record, dict)}
    while revision_id in existing_ids:
        revision_id = str(uuid.uuid4())
    updated = deepcopy(manifest)
    record = {
        "number": number,
        "revision_id": revision_id,
        "created_at": timestamp,
        "description": description,
        "lifecycle": "open",
        "approval": {"approved_at": None, "approved_by": None},
    }
    updated["revisions"].append(record)
    updated["state"]["current_revision"] = number
    updated["metadata"]["last_modified_at"] = timestamp
    _validate_project_state(updated)
    _validate_schema(updated)

    if request.dry_run:
        return RevisionCreateResult(
            project_root, revision_root, number, description, previous_revision,
            updated, effective_cd, source_plan, False,
        )

    prior_manifest = manifest_path.read_bytes()
    prior_manifest_mode = manifest_path.stat().st_mode & 0o777
    stage = create_staging_directory(revisions_root, f".{revision_name}.jl-stage-")
    manifest_fd, manifest_temp = create_staging_file(manifest_path.parent, f".{manifest_path.name}.")
    committed_directory = False
    manifest_replaced = False
    try:
        os.close(manifest_fd)
        if source_plan is not None:
            copy_from_plan(source_plan, stage)
        (stage / "Variants").mkdir()
        (stage / "Revision_Notes.md").write_text(
            _render_notes(number, description), encoding="utf-8", newline="\n"
        )
        manifest_temp.write_text(
            json.dumps(updated, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8", newline="\n",
        )
        if revision_root.exists() or revision_root.is_symlink():
            raise UnsafeOperationError(f"Revision destination already exists: {revision_root}")

        if _fail_requested("after-coordinated-backup"):
            raise _injected_failure("after-coordinated-backup")

        os.replace(stage, revision_root)
        committed_directory = True
        if _fail_requested("after-coordinated-directory"):
            raise _injected_failure("after-coordinated-directory")

        os.replace(manifest_temp, manifest_path)
        manifest_replaced = True
        if _fail_requested("after-coordinated-file"):
            raise _injected_failure("after-coordinated-file")
    except Exception:
        if manifest_replaced:
            _restore_manifest(manifest_path, prior_manifest, prior_manifest_mode)
            manifest_replaced = False
        if committed_directory and revision_root.exists():
            shutil.rmtree(revision_root, ignore_errors=True)
            committed_directory = False
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        if manifest_temp.exists():
            manifest_temp.unlink()

    return RevisionCreateResult(
        project_root, revision_root, number, description, previous_revision,
        updated, effective_cd, source_plan, True,
    )
