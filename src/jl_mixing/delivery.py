"""Authoritative cross-platform final-delivery planning and creation service."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import uuid
import zipfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from .approval import derive_project_stage
from .context import resolve_project, revision_root_for_number, studio_root as resolve_studio_root
from .errors import ContextError, UnsafeOperationError, ValidationError
from .filesystem_noise import path_contains_filesystem_noise
from .metadata import create_v11, now_iso8601
from .filesystem_noise import is_filesystem_noise_name
from .revision import _load_manifest, _validate_project_state, _validate_schema
from .transactions import (
    _fail_requested,
    _injected_failure,
    create_staging_directory,
    create_staging_file,
    reserve_staging_path,
)
from .versions import application_root

DeliveryMode = Literal["default", "overwrite", "clean"]


@dataclass(frozen=True)
class DeliverySelection:
    source: Path
    source_path: str
    name: str
    deliverable_type: str
    path: str


@dataclass(frozen=True)
class DeliveryExclusion:
    name: str
    reason: str


@dataclass(frozen=True)
class DeliveryPlan:
    selected: tuple[DeliverySelection, ...]
    excluded: tuple[DeliveryExclusion, ...]
    deletions: tuple[str, ...]
    old_files: tuple[str, ...]
    mode: DeliveryMode


@dataclass(frozen=True)
class DeliveryCreateRequest:
    project_root: Path
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    working_prefix: str = "WORK "
    overwrite: bool = False
    clean: bool = False
    make_zip: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class DeliveryCreateResult:
    project_root: Path
    delivery_root: Path
    revision_root: Path
    approved_revision: int
    current_revision: int
    previous_delivered_revision: int | None
    delivery_method: str
    plan: DeliveryPlan
    manifest: dict[str, Any]
    delivery_manifest: dict[str, Any] | None
    zip_name: str | None
    files_delivered: int
    project_stage: str
    created: bool


def _split_patterns(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        for item in value.split(","):
            item = item.strip()
            if not item:
                raise ValidationError("Empty include/exclude pattern is not allowed")
            result.append(item)
    return tuple(result)


def _normalize(name: str) -> str:
    return re.sub(r"[\s_-]+", " ", name.casefold()).strip()


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text) is not None


def classify_deliverable(name: str) -> str:
    text = _normalize(name)
    if _has_word(text, "stem") or _has_word(text, "stems"):
        return "stems"
    if _has_word(text, "instrumental"):
        return "instrumental"
    if _has_word(text, "acapella") or re.search(r"(?<![a-z0-9])a cappella(?![a-z0-9])", text):
        return "acapella"
    if re.search(r"(?<![a-z0-9])tv mix(?![a-z0-9])", text):
        return "tv_mix"
    if re.search(r"(?<![a-z0-9])performance mix(?![a-z0-9])", text):
        return "performance_mix"
    if _has_word(text, "master"):
        return "master"
    if re.search(r"(?<![a-z0-9])main mix(?![a-z0-9])", text):
        return "main_mix"
    return "unclassified"


def _safe_relative(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValidationError(f"Unsafe delivery path: {value!r}")
    pure = PurePosixPath(value)
    parts = value.split("/")
    if pure.is_absolute() or any(part in ("", ".", "..") for part in parts):
        raise ValidationError(f"Unsafe delivery path: {value}")
    return pure


def _regular_no_symlink(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink()
    except OSError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _recursive_listing(root: Path) -> tuple[str, ...]:
    if not root.exists():
        return ()
    items: list[str] = []
    for path in sorted(root.rglob("*"), key=lambda value: (value.relative_to(root).as_posix().casefold(), value.relative_to(root).as_posix())):
        suffix = "/" if path.is_dir() and not path.is_symlink() else ""
        items.append(path.relative_to(root).as_posix() + suffix)
    return tuple(items)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValidationError(f"{label} is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Unable to read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object: {path}")
    return value


def _copy_existing_no_follow(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    for item in source.iterdir():
        target = destination / item.name
        if item.is_symlink():
            try:
                os.symlink(os.readlink(item), target, target_is_directory=item.is_dir())
            except OSError as exc:
                raise ValidationError(f"Unable to preserve existing delivery symbolic link: {item}") from exc
        elif item.is_dir():
            shutil.copytree(item, target, symlinks=True)
        elif _regular_no_symlink(item):
            shutil.copy2(item, target, follow_symlinks=False)
        else:
            raise ValidationError(f"Unsupported existing delivery item: {item}")


def _remove_entry(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _generated_zip_pattern(project_id: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(project_id)}-rev-[0-9]{{2}}-[0-9]{{14}}\.zip$")


def _zip_stage(stage: Path, zip_name: str, project_id: str) -> None:
    archive = stage / zip_name
    generated = _generated_zip_pattern(project_id)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(stage.rglob("*"), key=lambda value: (value.relative_to(stage).as_posix().casefold(), value.relative_to(stage).as_posix())):
            relative = path.relative_to(stage).as_posix()
            if path == archive or generated.fullmatch(path.name):
                continue
            if path_contains_filesystem_noise(relative):
                continue
            if path.is_symlink():
                raise ValidationError(f"Symbolic links cannot be archived in a delivery ZIP: {path}")
            if path.is_dir():
                continue
            handle.write(path, relative)


def _uuid_available(studio_root: Path, candidate: str) -> bool:
    for path in studio_root.rglob("*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        metadata = document.get("metadata") if isinstance(document, dict) else None
        if isinstance(metadata, dict) and metadata.get("document_id") == candidate:
            return False
    return True


def _document_id(studio_root: Path) -> str:
    while True:
        candidate = str(uuid.uuid4())
        if _uuid_available(studio_root, candidate):
            return candidate


def _delivery_notes_template() -> Path:
    path = application_root() / "templates" / "Delivery_Notes.md"
    if not path.is_file():
        raise ContextError(f"Required template not found: {path}")
    return path


def plan_delivery(
    revision_root: Path,
    delivery_root: Path,
    project_manifest: dict[str, Any],
    *,
    mode: DeliveryMode,
    working_prefix: str,
    includes: tuple[str, ...],
    excludes: tuple[str, ...],
    zip_name: str | None,
) -> DeliveryPlan:
    if revision_root.is_symlink() or not revision_root.is_dir():
        raise ValidationError(f"Revision directory is missing or unsafe: {revision_root}")
    include_patterns = _split_patterns(includes)
    exclude_patterns = _split_patterns(excludes)
    selected: list[DeliverySelection] = []
    excluded: list[DeliveryExclusion] = []

    def consider_file(item: Path, source_path: str) -> None:
        if is_filesystem_noise_name(item.name):
            return
        if item.is_symlink():
            raise ValidationError(f"Symbolic links are not allowed in a delivery source: {item}")
        if not _regular_no_symlink(item):
            raise ValidationError(f"Unsupported source item: {item}")
        if working_prefix and item.name.startswith(working_prefix):
            excluded.append(DeliveryExclusion(item.name, "working prefix"))
            return
        if include_patterns and not any(fnmatch.fnmatchcase(item.name, pattern) for pattern in include_patterns):
            excluded.append(DeliveryExclusion(item.name, "include pattern"))
            return
        if exclude_patterns and any(fnmatch.fnmatchcase(item.name, pattern) for pattern in exclude_patterns):
            excluded.append(DeliveryExclusion(item.name, "exclude pattern"))
            return
        kind = classify_deliverable(item.name)
        relative = f"Stems/{item.name}" if kind == "stems" else item.name
        selected.append(DeliverySelection(item, source_path, item.name, kind, relative))

    for item in sorted(revision_root.iterdir(), key=lambda path: (path.name.casefold(), path.name)):
        if is_filesystem_noise_name(item.name):
            continue
        if item.name == "Revision_Notes.md":
            excluded.append(DeliveryExclusion(item.name, "revision notes"))
            continue
        if item.is_symlink():
            raise ValidationError(f"Symbolic links are not allowed in a delivery source: {item}")
        if item.name == "Variants" and item.is_dir():
            for variant in sorted(item.iterdir(), key=lambda path: (path.name.casefold(), path.name)):
                if is_filesystem_noise_name(variant.name):
                    continue
                if variant.is_dir() and not variant.is_symlink():
                    raise ValidationError(f"Subdirectories are not allowed in revision Variants: {variant}")
                consider_file(variant, f"Variants/{variant.name}")
            continue
        if item.is_dir():
            raise ValidationError(f"Subdirectories are not allowed in a delivery source: {item}")
        consider_file(item, item.name)

    if not selected:
        raise ValidationError("No deliverable files were found after applying filters")
    seen: dict[str, str] = {}
    for record in selected:
        key = record.path.casefold()
        if key in seen:
            raise ValidationError(f"Case-insensitive destination collision: {seen[key]} and {record.path}")
        seen[key] = record.path

    delivery_manifest_path = delivery_root / "delivery-manifest.json"
    old_files: tuple[str, ...] = ()
    if mode == "default":
        if delivery_manifest_path.exists() or delivery_manifest_path.is_symlink():
            raise ValidationError("A final-delivery package already exists. Use --overwrite or --clean")
        for record in selected:
            destination = delivery_root.joinpath(*_safe_relative(record.path).parts)
            if destination.exists() or destination.is_symlink():
                raise ValidationError(f"Destination is already occupied: {destination}")
        if zip_name and ((delivery_root / zip_name).exists() or (delivery_root / zip_name).is_symlink()):
            raise ValidationError(f"ZIP destination already exists: {delivery_root / zip_name}")
    elif mode == "overwrite":
        prior = _load_json(delivery_manifest_path, "prior delivery manifest")
        records = prior.get("files")
        if not isinstance(records, list):
            raise ValidationError("--overwrite requires a valid prior delivery manifest")
        extracted: list[str] = []
        for record in records:
            if isinstance(record, dict) and isinstance(record.get("path"), str):
                extracted.append(record["path"])
        old_files = tuple(extracted)
        old_map = {path.casefold(): path for path in old_files}
        for record in selected:
            destination = delivery_root.joinpath(*_safe_relative(record.path).parts)
            if (destination.exists() or destination.is_symlink()) and record.path.casefold() not in old_map:
                raise ValidationError(f"Destination is occupied by an untracked item: {destination}")
    elif mode != "clean":
        raise ValidationError(f"Unknown delivery replacement mode: {mode}")

    requested = project_manifest.get("delivery", {}).get("requested_deliverables", [])
    if not isinstance(requested, list):
        requested = []
    fixed = ["stems", "instrumental", "acapella", "tv_mix", "performance_mix", "master", "main_mix", "unclassified"]
    order: list[str] = []
    for item in [*requested, *fixed]:
        if isinstance(item, str) and item not in order:
            order.append(item)
    rank = {item: index for index, item in enumerate(order)}
    selected.sort(key=lambda record: (rank.get(record.deliverable_type, 999), record.path.casefold(), record.path))
    deletions = _recursive_listing(delivery_root) if mode == "clean" else ()
    return DeliveryPlan(tuple(selected), tuple(excluded), deletions, old_files, mode)


def _stage_delivery(
    plan: DeliveryPlan,
    project_manifest: dict[str, Any],
    delivery_root: Path,
    stage: Path,
    *,
    document_id: str,
    timestamp: str,
    zip_name: str | None,
) -> dict[str, Any]:
    if any(stage.iterdir()):
        raise ValidationError(f"Staging directory is not empty: {stage}")
    if plan.mode != "clean":
        _copy_existing_no_follow(delivery_root, stage)
    else:
        (stage / "Stems").mkdir(parents=True, exist_ok=True)
        shutil.copy2(_delivery_notes_template(), stage / "Delivery_Notes.md")

    stems = stage / "Stems"
    if stems.exists() or stems.is_symlink():
        if stems.is_symlink() or not stems.is_dir():
            raise ValidationError(f"Stems path is unsafe: {stems}")
    else:
        stems.mkdir(parents=True)
    notes = stage / "Delivery_Notes.md"
    if notes.exists() or notes.is_symlink():
        if not _regular_no_symlink(notes):
            raise ValidationError(f"Delivery notes path is unsafe: {notes}")
    else:
        shutil.copy2(_delivery_notes_template(), notes)

    delivery_manifest_path = stage / "delivery-manifest.json"
    if delivery_manifest_path.exists() or delivery_manifest_path.is_symlink():
        _remove_entry(delivery_manifest_path)
    if plan.mode == "overwrite":
        for relative in plan.old_files:
            path = stage.joinpath(*_safe_relative(relative).parts)
            if path.exists() or path.is_symlink():
                _remove_entry(path)

    records: list[dict[str, Any]] = []
    for record in plan.selected:
        source = record.source
        if not _regular_no_symlink(source):
            raise ValidationError(f"Source changed or became unsafe: {source}")
        before = _sha256(source)
        destination = stage.joinpath(*_safe_relative(record.path).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            if plan.mode == "default":
                raise ValidationError(f"Staged destination conflict: {destination}")
            _remove_entry(destination)
        shutil.copy2(source, destination, follow_symlinks=False)
        after = _sha256(destination)
        if before != after:
            raise ValidationError(f"Copy verification failed: {source}")
        records.append({
            "path": record.path,
            "source_path": record.source_path,
            "deliverable_type": record.deliverable_type,
            "size_bytes": destination.stat().st_size,
            "sha256": after,
        })

    approved_revision = project_manifest["state"]["approved_revision"]
    revision = next(
        (item for item in project_manifest["revisions"] if item.get("number") == approved_revision),
        None,
    )
    if not isinstance(revision, dict):
        raise ValidationError(f"Approved Revision {approved_revision} does not exist")
    delivery_manifest: dict[str, Any] = {
        "metadata": create_v11(
            "mixing-delivery",
            mutability="immutable",
            document_id=document_id,
            timestamp=timestamp,
        ),
        "project": {
            "project_document_id": project_manifest["metadata"]["document_id"],
            "project_id": project_manifest["project_id"],
            "project_name": project_manifest["project_name"],
        },
        "client": {
            "client_document_id": project_manifest["client"]["client_document_id"],
            "client_id": project_manifest["client"]["client_id"],
        },
        "revision": {
            "number": approved_revision,
            "revision_id": revision["revision_id"],
            "description": revision["description"],
            "approval": deepcopy(revision["approval"]),
        },
        "delivery": {"method": project_manifest["delivery"]["method"]},
        "files": records,
    }
    delivery_manifest_path.write_text(
        json.dumps(delivery_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if zip_name is not None:
        _zip_stage(stage, zip_name, project_manifest["project_id"])
    return delivery_manifest


def _restore_file_bytes(path: Path, data: bytes, mode: int) -> None:
    fd, temp = create_staging_file(path.parent, f".{path.name}.jl-restore-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _commit_delivery_and_manifest(stage: Path, delivery_root: Path, manifest_temp: Path, manifest_path: Path) -> None:
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise UnsafeOperationError(f"Project manifest is missing or unsafe: {manifest_path}")
    prior_manifest = manifest_path.read_bytes()
    prior_manifest_mode = manifest_path.stat().st_mode & 0o777

    parent = delivery_root.parent
    backup = reserve_staging_path(parent, f".{delivery_root.name}.jl-backup-")
    moved_old = False
    installed_new = False
    manifest_replaced = False
    try:
        if delivery_root.exists() or delivery_root.is_symlink():
            if delivery_root.is_symlink() or not delivery_root.is_dir():
                raise UnsafeOperationError(f"Delivery root is missing or unsafe: {delivery_root}")
            os.replace(delivery_root, backup)
            moved_old = True

        if _fail_requested("after-coordinated-backup"):
            raise _injected_failure("after-coordinated-backup")

        os.replace(stage, delivery_root)
        installed_new = True
        if _fail_requested("after-coordinated-directory"):
            raise _injected_failure("after-coordinated-directory")

        os.replace(manifest_temp, manifest_path)
        manifest_replaced = True
        if _fail_requested("after-coordinated-file"):
            raise _injected_failure("after-coordinated-file")

        if moved_old and backup.exists():
            shutil.rmtree(backup)
            moved_old = False
    except Exception:
        if manifest_replaced:
            _restore_file_bytes(manifest_path, prior_manifest, prior_manifest_mode)
            manifest_replaced = False
        if installed_new and delivery_root.exists():
            shutil.rmtree(delivery_root, ignore_errors=True)
            installed_new = False
        if moved_old and backup.exists() and not delivery_root.exists():
            os.replace(backup, delivery_root)
            moved_old = False
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)


def create_delivery(request: DeliveryCreateRequest) -> DeliveryCreateResult:
    if request.overwrite and request.clean:
        raise ValidationError("--overwrite and --clean are mutually exclusive.")
    if request.working_prefix == "":
        raise ValidationError("--working-prefix cannot be empty.")
    mode: DeliveryMode = "clean" if request.clean else "overwrite" if request.overwrite else "default"

    project_root = resolve_project(request.project_root, Path.cwd())
    manifest_path = project_root / "00_Admin" / "project-manifest.json"
    manifest = _load_manifest(project_root)
    current_revision = _validate_project_state(manifest)
    state = manifest["state"]
    approved_revision = state.get("approved_revision")
    if not isinstance(approved_revision, int) or isinstance(approved_revision, bool) or approved_revision < 1:
        raise ValidationError("A revision must be approved before delivery can be created.")
    revision_root = revision_root_for_number(project_root, approved_revision)
    delivery_root = project_root / "05_Final_Delivery"
    if delivery_root.is_symlink() or not delivery_root.is_dir():
        raise ContextError(f"Delivery root is missing or unsafe: {delivery_root}")

    timestamp = now_iso8601()
    local_timestamp = datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
    zip_name = f"{manifest['project_id']}-rev-{approved_revision:02d}-{local_timestamp}.zip" if request.make_zip else None
    plan = plan_delivery(
        revision_root,
        delivery_root,
        manifest,
        mode=mode,
        working_prefix=request.working_prefix,
        includes=request.include,
        excludes=request.exclude,
        zip_name=zip_name,
    )
    previous_delivered = state.get("delivered_revision")
    delivery_method = manifest["delivery"]["method"]

    updated_manifest = deepcopy(manifest)
    updated_manifest["state"]["delivered_revision"] = approved_revision
    updated_manifest["metadata"]["last_modified_at"] = timestamp
    _validate_project_state(updated_manifest)
    _validate_schema(updated_manifest)

    if request.dry_run:
        return DeliveryCreateResult(
            project_root, delivery_root, revision_root, approved_revision, current_revision,
            previous_delivered, delivery_method, plan, updated_manifest, None, zip_name,
            0, derive_project_stage(updated_manifest), False,
        )

    studio_root = resolve_studio_root(project_root)
    document_id = _document_id(studio_root)
    stage = create_staging_directory(delivery_root.parent, f".{delivery_root.name}.jl-stage-")
    manifest_fd, manifest_temp = create_staging_file(manifest_path.parent, f".{manifest_path.name}.")
    os.close(manifest_fd)
    try:
        delivery_manifest = _stage_delivery(
            plan,
            manifest,
            delivery_root,
            stage,
            document_id=document_id,
            timestamp=timestamp,
            zip_name=zip_name,
        )
        schema_path = application_root() / "schemas" / "delivery-manifest.schema.json"
        try:
            import jsonschema
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(delivery_manifest)
        except (OSError, json.JSONDecodeError) as exc:
            raise ContextError(f"Required delivery schema is unreadable: {schema_path}") from exc
        except jsonschema.ValidationError as exc:
            raise ValidationError(f"Generated delivery manifest failed schema validation: {exc.message}") from exc
        manifest_temp.write_text(
            json.dumps(updated_manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        _commit_delivery_and_manifest(stage, delivery_root, manifest_temp, manifest_path)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        if manifest_temp.exists():
            manifest_temp.unlink()
        raise
    finally:
        if manifest_temp.exists():
            manifest_temp.unlink()

    return DeliveryCreateResult(
        project_root, delivery_root, revision_root, approved_revision, current_revision,
        previous_delivered, delivery_method, plan, updated_manifest, delivery_manifest, zip_name,
        len(plan.selected), derive_project_stage(updated_manifest), True,
    )
