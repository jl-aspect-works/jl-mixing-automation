"""Authoritative cross-platform project creation service."""

from __future__ import annotations

import json
import shutil
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import jsonschema

from .context import studio_root as resolve_studio_root
from .errors import ContextError, UnsafeOperationError, ValidationError
from .metadata import create_v11, now_iso8601, validate_v11
from .naming import sanitize_folder_name, slugify
from .paths import assert_no_case_insensitive_child_collision, assert_no_symlink_components
from .source_import import SourcePlan, build_plan, copy_from_plan
from .transactions import commit_new_directory, create_staging_directory
from .validation import require_bit_depth, require_deliverables, require_file_format, require_sample_rate, require_slug
from .versions import application_root


@dataclass(frozen=True)
class ProjectCreateRequest:
    client_root: Path
    project_name: str
    project_id: str | None = None
    artist: str | None = None
    album: str = ""
    producer: str = ""
    engineer: str | None = None
    bpm: float | int | None = None
    musical_key: str = ""
    time_signature: str = ""
    sample_rate: int | None = None
    bit_depth: int | None = None
    file_format: str | None = None
    deadline: str | None = None
    deliverables: list[str] | None = None
    description: str = ""
    source: Path | None = None
    change_directory: bool | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class ProjectCreateResult:
    project_root: Path
    manifest: dict[str, Any]
    client_snapshot: dict[str, Any]
    initial_revision_root: Path
    client_root: Path
    studio_root: Path
    effective_cd: bool
    source_plan: SourcePlan | None
    created: bool


def _load_json(path: Path, schema: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContextError(f"Required configuration not found or unsafe: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid JSON document: {path}") from exc
    metadata = document.get("metadata")
    validate_v11(metadata, schema, mutability="mutable")
    return document


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must not be empty.")
    return value.strip()


def _optional_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _validate_deadline(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"Deadline must be a valid calendar date in YYYY-MM-DD form: {value}") from exc
    if parsed.isoformat() != value:
        raise ValidationError(f"Deadline must be a valid calendar date in YYYY-MM-DD form: {value}")
    return value


def _validate_bpm(value: float | int | None) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValidationError(f"BPM must be a positive number: {value}")
    return value


def _project_id_available(projects_root: Path, candidate: str) -> None:
    wanted = candidate.casefold()
    for manifest in projects_root.glob("*/00_Admin/project-manifest.json"):
        if manifest.is_symlink() or not manifest.is_file():
            continue
        try:
            existing = json.loads(manifest.read_text(encoding="utf-8")).get("project_id")
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(existing, str) and existing.casefold() == wanted:
            raise ValidationError(f"Project ID already exists for this client: {candidate}")


def _validate_schema(filename: str, document: dict[str, Any]) -> None:
    schema_path = application_root() / "schemas" / filename
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(document)
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextError(f"Required schema is unreadable: {schema_path}") from exc
    except jsonschema.ValidationError as exc:
        raise ValidationError(f"Generated document failed {filename}: {exc.message}") from exc


def _write_template(name: str, destination: Path, replacements: dict[str, str] | None = None) -> None:
    source = application_root() / "templates" / name
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContextError(f"Required template not found: {source}") from exc
    for key, value in (replacements or {}).items():
        text = text.replace("{{" + key + "}}", value)
    destination.write_text(text, encoding="utf-8", newline="\n")


def _resolve_inputs(request: ProjectCreateRequest) -> dict[str, Any]:
    client_root = request.client_root.expanduser().resolve(strict=False)
    client = _load_json(client_root / "client.json", "mixing-client")
    studio_root = resolve_studio_root(client_root)
    studio = _load_json(studio_root / "Studio" / "studio.json", "mixing-studio")
    clients_root = studio_root / "Clients"
    try:
        client_root.relative_to(clients_root)
    except ValueError as exc:
        raise ContextError(f"Selected client is not owned by the resolved studio: {client_root}") from exc
    assert_no_symlink_components(studio_root, client_root)

    projects_root = client_root / "Projects"
    if projects_root.is_symlink() or not projects_root.is_dir():
        raise ContextError(f"Client Projects directory is missing or unsafe: {projects_root}")
    assert_no_symlink_components(studio_root, projects_root)

    project_name = _nonempty(request.project_name, "project name")
    folder_name = sanitize_folder_name(project_name)
    project_id = require_slug(request.project_id if request.project_id is not None else slugify(project_name), label="Project ID")
    _project_id_available(projects_root, project_id)
    assert_no_case_insensitive_child_collision(projects_root, folder_name)
    project_root = projects_root / folder_name
    if project_root.exists() or project_root.is_symlink():
        raise UnsafeOperationError(f"Project destination already exists: {project_root}")

    client_name = _nonempty(client.get("client_name"), "client name")
    client_id = _nonempty(client.get("client_id"), "client ID")
    client_metadata = client.get("metadata") if isinstance(client.get("metadata"), dict) else {}
    client_document_id = _nonempty(client_metadata.get("document_id"), "client document ID")
    client_defaults = client.get("defaults") if isinstance(client.get("defaults"), dict) else {}
    client_audio = client_defaults.get("audio") if isinstance(client_defaults.get("audio"), dict) else {}
    client_delivery = client_defaults.get("delivery") if isinstance(client_defaults.get("delivery"), dict) else {}
    studio_defaults = studio.get("defaults") if isinstance(studio.get("defaults"), dict) else {}
    studio_audio = studio_defaults.get("audio") if isinstance(studio_defaults.get("audio"), dict) else {}
    studio_delivery = studio_defaults.get("delivery") if isinstance(studio_defaults.get("delivery"), dict) else {}

    artist = (_optional_text(client_defaults.get("artist")) or client_name) if request.artist is None else _nonempty(request.artist, "Artist")
    engineer = _optional_text(studio_defaults.get("mix_engineer")) if request.engineer is None else _optional_text(request.engineer)

    sample_rate_source = request.sample_rate if request.sample_rate is not None else client_audio.get("sample_rate")
    if sample_rate_source in {None, ""}:
        sample_rate_source = studio_audio.get("sample_rate")
    bit_depth_source = request.bit_depth if request.bit_depth is not None else client_audio.get("bit_depth")
    if bit_depth_source in {None, ""}:
        bit_depth_source = studio_audio.get("bit_depth")
    format_source = request.file_format if request.file_format is not None else client_audio.get("file_format")
    if format_source in {None, ""}:
        format_source = studio_audio.get("file_format")
    sample_rate = require_sample_rate(sample_rate_source)
    bit_depth = require_bit_depth(bit_depth_source)
    file_format = require_file_format(format_source)

    delivery_method = _nonempty(client_delivery.get("method") or studio_delivery.get("method"), "delivery method")
    inherited_deliverables = client_delivery.get("requested_deliverables")
    if not isinstance(inherited_deliverables, list) or not inherited_deliverables:
        inherited_deliverables = studio_delivery.get("requested_deliverables")
    deliverables = require_deliverables(request.deliverables if request.deliverables is not None else inherited_deliverables)

    cli = studio.get("cli") if isinstance(studio.get("cli"), dict) else {}
    effective_cd = request.change_directory if request.change_directory is not None else cli.get("change_directory_after_create") is True

    source_plan = build_plan(request.source) if request.source is not None else None
    if source_plan is not None and source_plan.source_type == "directory":
        try:
            projects_root.resolve(strict=False).relative_to(source_plan.source)
        except ValueError:
            pass
        else:
            raise UnsafeOperationError(f"Source directory cannot contain the client Projects directory: {source_plan.source}")

    return {
        "studio_root": studio_root,
        "client_root": client_root,
        "client": client,
        "project_root": project_root,
        "project_name": project_name,
        "project_id": project_id,
        "client_name": client_name,
        "client_id": client_id,
        "client_document_id": client_document_id,
        "artist": artist,
        "engineer": engineer,
        "sample_rate": sample_rate,
        "bit_depth": bit_depth,
        "file_format": file_format,
        "delivery_method": delivery_method,
        "deliverables": deliverables,
        "effective_cd": effective_cd,
        "source_plan": source_plan,
    }


def create_project(request: ProjectCreateRequest) -> ProjectCreateResult:
    values = _resolve_inputs(request)
    bpm = _validate_bpm(request.bpm)
    deadline = _validate_deadline(request.deadline)
    timestamp = now_iso8601()

    manifest: dict[str, Any] = {
        "metadata": create_v11("mixing-project", mutability="mutable", timestamp=timestamp),
        "project_id": values["project_id"],
        "project_name": values["project_name"],
        "client": {"client_document_id": values["client_document_id"], "client_id": values["client_id"]},
        "artist": values["artist"],
        "album": _optional_text(request.album),
        "producer": _optional_text(request.producer),
        "mix_engineer": values["engineer"],
        "music": {"bpm": bpm, "key": _optional_text(request.musical_key), "time_signature": _optional_text(request.time_signature)},
        "audio": {"sample_rate": values["sample_rate"], "bit_depth": values["bit_depth"], "file_format": values["file_format"]},
        "delivery": {"method": values["delivery_method"], "requested_deliverables": values["deliverables"]},
        "schedule": {"deadline": deadline},
        "creative_direction": _optional_text(request.description),
        "state": {"current_revision": 1, "approved_revision": None, "delivered_revision": None},
        "revisions": [{
            "number": 1,
            "revision_id": str(uuid.uuid4()),
            "created_at": timestamp,
            "description": "Initial mix",
            "approval": {"approved_at": None, "approved_by": None},
        }],
    }
    snapshot: dict[str, Any] = {
        "metadata": create_v11("mixing-client-profile-snapshot", mutability="immutable", timestamp=timestamp),
        "source_client": {
            "client_document_id": values["client_document_id"],
            "client_id": values["client_id"],
            "client_name": values["client_name"],
        },
        "defaults": deepcopy(values["client"].get("defaults") if isinstance(values["client"].get("defaults"), dict) else {}),
    }
    validate_v11(manifest["metadata"], "mixing-project", mutability="mutable")
    validate_v11(snapshot["metadata"], "mixing-client-profile-snapshot", mutability="immutable")
    _validate_schema("project-manifest.schema.json", manifest)
    _validate_schema("client-profile-snapshot.schema.json", snapshot)

    project_root: Path = values["project_root"]
    initial_revision_root = project_root / "04_Revisions" / "Revision_01"
    if request.dry_run:
        return ProjectCreateResult(project_root, manifest, snapshot, initial_revision_root, values["client_root"], values["studio_root"], values["effective_cd"], values["source_plan"], False)

    projects_root = values["client_root"] / "Projects"
    stage = create_staging_directory(projects_root, f".{project_root.name}.jl-stage-")
    try:
        for relative in (
            "00_Admin",
            "01_Client_Files/Original_Delivery",
            "01_Client_Files/References",
            "01_Client_Files/Documentation",
            "02_Audio_Preparation/Working_Audio",
            "02_Audio_Preparation/Rejected_Files",
            "03_DAW_Project",
            "04_Revisions/Revision_01",
            "04_Revisions/Revision_01/Variants",
            "05_Final_Delivery/Stems",
            "06_Recall/External_Files",
            "06_Recall/Screenshots",
        ):
            stage.joinpath(*relative.split("/")).mkdir(parents=True, exist_ok=True)

        (stage / "00_Admin" / "project-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        (stage / "00_Admin" / "client-profile-snapshot.json").write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        _write_template("Intake_Report.md", stage / "00_Admin" / "Intake_Report.md")
        _write_template("Project_Notes.md", stage / "00_Admin" / "Project_Notes.md")
        _write_template("Preparation_Report.md", stage / "02_Audio_Preparation" / "Preparation_Report.md")
        _write_template("Revision_Notes.md", stage / "04_Revisions" / "Revision_01" / "Revision_Notes.md", {"REVISION_NUMBER": "1", "REVISION_DESCRIPTION": "Initial mix"})
        _write_template("Delivery_Notes.md", stage / "05_Final_Delivery" / "Delivery_Notes.md")
        _write_template("Recall_Sheet.md", stage / "06_Recall" / "Recall_Sheet.md")
        if values["source_plan"] is not None:
            copy_from_plan(values["source_plan"], stage / "01_Client_Files" / "Original_Delivery")
        if project_root.exists() or project_root.is_symlink():
            raise UnsafeOperationError(f"Project destination already exists: {project_root}")
        commit_new_directory(stage, project_root)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise

    return ProjectCreateResult(project_root, manifest, snapshot, initial_revision_root, values["client_root"], values["studio_root"], values["effective_cd"], values["source_plan"], True)
