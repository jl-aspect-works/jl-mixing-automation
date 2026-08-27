"""Managed Client Files import and Audio Prep reset planning/execution."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

from .errors import UnsafeOperationError, ValidationError
from .transactions import create_staging_directory

ORIGINAL_ROOT = Path("01_Client_Files") / "Original_Delivery"
AUDIO_ROOT = Path("02_Audio_Preparation") / "Working_Audio"
INTAKE_CACHE = Path("00_Admin") / "intake-validation-cache.json"
AUDIO_CACHE = Path("00_Admin") / "audio-prep-validation-cache.json"
ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class SourceFile:
    relative_path: str
    source_path: Path | None
    zip_member: str | None
    size: int
    fingerprint: str


def _safe_relative(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafeOperationError(f"Unsafe relative path: {value}")
    if ":" in path.parts[0]:
        raise UnsafeOperationError(f"Unsafe drive-qualified path: {value}")
    return path.as_posix()


def _safe_source(raw: Path, *, directory: bool = False) -> Path:
    candidate = raw.expanduser()
    if candidate.is_symlink():
        raise UnsafeOperationError(f"Import source may not be a symlink: {candidate}")
    resolved = candidate.resolve()
    valid = resolved.is_dir() if directory else resolved.is_file()
    if not valid:
        kind = "folder" if directory else "regular file"
        raise UnsafeOperationError(f"Import source is not a {kind}: {resolved}")
    return resolved


def _managed_destination(project_root: Path, relative: str) -> Path:
    safe = _safe_relative(relative)
    destination = project_root / Path(safe)
    current = project_root
    for part in Path(safe).parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise UnsafeOperationError(f"Managed destination traverses a symlink: {current}")
        if current.exists() and not current.is_dir():
            raise UnsafeOperationError(f"Managed destination parent is not a directory: {current}")
    if destination.is_symlink():
        raise UnsafeOperationError(f"Managed destination may not be a symlink: {destination}")
    return destination


def _file_state(path: Path) -> str:
    if not path.exists():
        return "missing"
    if path.is_symlink() or not path.is_file():
        raise UnsafeOperationError(f"Managed destination is not a regular file: {path}")
    info = path.stat()
    return f"file:{info.st_size}:{info.st_mtime_ns}"


def _source_fingerprint(path: Path) -> str:
    info = path.stat()
    return f"file:{info.st_size}:{info.st_mtime_ns}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audio_prep_content_match(project_root: Path, source: Path) -> str | None:
    """Return the one Audio Prep path with identical content, regardless of rename."""
    audio_root = project_root / AUDIO_ROOT
    if not audio_root.exists():
        return None
    if audio_root.is_symlink() or not audio_root.is_dir():
        raise UnsafeOperationError(f"Audio Prep root is unavailable or unsafe: {audio_root}")

    source_hash = _sha256_file(source)
    matches: list[str] = []
    for current, dirs, names in os.walk(audio_root, followlinks=False):
        current_path = Path(current)
        for directory in dirs:
            if (current_path / directory).is_symlink():
                raise UnsafeOperationError(f"Audio Prep does not allow symlink traversal: {current_path / directory}")
        for name in names:
            candidate = current_path / name
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if candidate.stat().st_size != source.stat().st_size:
                continue
            if _sha256_file(candidate) == source_hash:
                relative = candidate.relative_to(audio_root).as_posix()
                matches.append((AUDIO_ROOT / Path(relative)).as_posix())

    if len(matches) > 1:
        raise ValidationError(
            f"Multiple Audio Prep files match Original Delivery content for {_safe_relative(source.relative_to(project_root / ORIGINAL_ROOT).as_posix())}; repair is required before reset."
        )
    return matches[0] if matches else None


def _collect_files(source_kind: str, sources: tuple[Path, ...]) -> list[SourceFile]:
    files: list[SourceFile] = []
    seen: set[str] = set()

    def add(relative: str, source: Path | None, zip_member: str | None, size: int, fingerprint: str) -> None:
        safe = _safe_relative(relative)
        key = safe.casefold()
        if key in seen:
            raise ValidationError(f"Duplicate imported relative path: {safe}")
        seen.add(key)
        files.append(SourceFile(safe, source, zip_member, size, fingerprint))

    if source_kind == "files":
        if not sources:
            raise ValidationError("At least one source file is required.")
        for raw in sources:
            source = _safe_source(raw)
            add(source.name, source, None, source.stat().st_size, _source_fingerprint(source))
    elif source_kind == "folder":
        if len(sources) != 1:
            raise ValidationError("Folder import requires exactly one source folder.")
        root = _safe_source(sources[0], directory=True)
        for current, dirs, names in os.walk(root, followlinks=False):
            current_path = Path(current)
            for directory in dirs:
                if (current_path / directory).is_symlink():
                    raise UnsafeOperationError(f"Folder import does not allow symlinks: {current_path / directory}")
            for name in names:
                source = current_path / name
                if source.is_symlink() or not source.is_file():
                    raise UnsafeOperationError(f"Folder import does not allow special files: {source}")
                relative = source.relative_to(root).as_posix()
                add(relative, source, None, source.stat().st_size, _source_fingerprint(source))
    elif source_kind == "zip":
        if len(sources) != 1:
            raise ValidationError("ZIP import requires exactly one source archive.")
        archive = _safe_source(sources[0])
        try:
            with zipfile.ZipFile(archive) as handle:
                for info in handle.infolist():
                    mode = (info.external_attr >> 16) & 0xFFFF
                    if info.is_dir():
                        continue
                    if stat.S_ISLNK(mode) or (mode and not stat.S_ISREG(mode)):
                        raise UnsafeOperationError(f"ZIP contains an unsupported special entry: {info.filename}")
                    relative = _safe_relative(info.filename)
                    add(relative, archive, info.filename, info.file_size, f"zip:{info.CRC}:{info.file_size}")
        except zipfile.BadZipFile as exc:
            raise ValidationError(f"Invalid ZIP archive: {archive}") from exc
    else:
        raise ValidationError(f"Unsupported import source kind: {source_kind}")

    if not files:
        raise ValidationError("Import source contains no files.")
    files.sort(key=lambda item: item.relative_path.casefold())
    return files


def _item(project_root: Path, item_id: str, area: str, relative: str, source: SourceFile, *, depends_on: str | None = None) -> dict[str, Any]:
    destination = _managed_destination(project_root, relative)
    state = _file_state(destination)
    conflict = state != "missing"
    result: dict[str, Any] = {
        "id": item_id,
        "area": area,
        "source_relative_path": source.relative_path,
        "destination_relative_path": relative,
        "action": "replace_candidate" if conflict else "create",
        "conflict": conflict,
        "destination_state": state,
        "size_bytes": source.size,
    }
    if depends_on:
        result["depends_on"] = depends_on
    return result


def _plan_id(operation: str, source_kind: str, sources: Iterable[Path], files: Iterable[SourceFile], items: Iterable[dict[str, Any]]) -> str:
    payload = {
        "operation": operation,
        "source_kind": source_kind,
        "sources": [str(path.expanduser().absolute()) for path in sources],
        "files": [{"path": item.relative_path, "fingerprint": item.fingerprint} for item in files],
        "items": [{"id": item["id"], "destination_state": item["destination_state"], "destination_relative_path": item["destination_relative_path"]} for item in items],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _serialized_source(source: SourceFile) -> dict[str, Any]:
    return {
        "relative_path": source.relative_path,
        "source_path": str(source.source_path) if source.source_path else None,
        "zip_member": source.zip_member,
        "size": source.size,
        "fingerprint": source.fingerprint,
    }


def plan_import(project_root: Path, source_kind: str, sources: tuple[Path, ...]) -> dict[str, Any]:
    files = _collect_files(source_kind, sources)
    items: list[dict[str, Any]] = []
    for index, source in enumerate(files):
        original_rel = (ORIGINAL_ROOT / Path(source.relative_path)).as_posix()
        audio_rel = (AUDIO_ROOT / Path(source.relative_path)).as_posix()
        original_id = f"original:{index}"
        items.append(_item(project_root, original_id, "original_delivery", original_rel, source))
        items.append(_item(project_root, f"audio:{index}", "audio_prep", audio_rel, source, depends_on=original_id))
    return {
        "operation": "client.files.import",
        "source_kind": source_kind,
        "sources": [str(path.expanduser().absolute()) for path in sources],
        "plan_id": _plan_id("client.files.import", source_kind, sources, files, items),
        "files": [_serialized_source(source) for source in files],
        "items": items,
    }


def plan_reset(project_root: Path, relative_paths: tuple[str, ...]) -> dict[str, Any]:
    files: list[SourceFile] = []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(relative_paths):
        relative = _safe_relative(raw)
        key = relative.casefold()
        if key in seen:
            raise ValidationError(f"Duplicate reset path: {relative}")
        seen.add(key)
        source = _managed_destination(project_root, (ORIGINAL_ROOT / Path(relative)).as_posix())
        if not source.is_file():
            raise ValidationError(f"Original Delivery file not found: {relative}")
        source_file = SourceFile(relative, source, None, source.stat().st_size, _source_fingerprint(source))
        files.append(source_file)
        matched_audio_rel = _audio_prep_content_match(project_root, source)
        dest_rel = matched_audio_rel or (AUDIO_ROOT / Path(relative)).as_posix()
        items.append(_item(project_root, f"audio:{index}", "audio_prep", dest_rel, source_file))
    if not files:
        raise ValidationError("At least one Original Delivery file is required.")
    return {
        "operation": "audio.prep.reset",
        "source_kind": "original_delivery",
        "sources": [source.relative_path for source in files],
        "plan_id": _plan_id("audio.prep.reset", "original_delivery", (), files, items),
        "files": [_serialized_source(source) for source in files],
        "items": items,
    }


def _decisions(plan: dict[str, Any], decisions: dict[str, str]) -> dict[str, str]:
    conflict_ids = {item["id"] for item in plan["items"] if item["conflict"]}
    unknown = set(decisions) - conflict_ids
    if unknown:
        raise ValidationError(f"Decision references unknown conflict: {sorted(unknown)[0]}")
    missing = conflict_ids - set(decisions)
    if missing:
        raise ValidationError(f"Missing conflict decision: {sorted(missing)[0]}")
    for value in decisions.values():
        if value not in {"replace", "skip"}:
            raise ValidationError(f"Unsupported conflict decision: {value}")
    return decisions


def _stage_source(source: SourceFile, stage: Path) -> Path:
    target = stage / Path(source.relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.zip_member is None:
        assert source.source_path is not None
        shutil.copyfile(source.source_path, target)
    else:
        assert source.source_path is not None
        with zipfile.ZipFile(source.source_path) as archive, archive.open(source.zip_member) as input_stream, target.open("wb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream)
    return target


def _invalidate(project_root: Path, changed_original: bool, changed_audio: bool) -> list[str]:
    invalidated: list[str] = []
    for changed, relative in ((changed_original, INTAKE_CACHE), (changed_audio, AUDIO_CACHE)):
        if not changed:
            continue
        path = project_root / relative
        if path.is_symlink():
            raise UnsafeOperationError(f"Validation cache path may not be a symlink: {path}")
        if path.exists() and path.is_file():
            path.unlink()
        invalidated.append(relative.as_posix())
    return invalidated


def execute_plan(
    project_root: Path,
    plan: dict[str, Any],
    decisions: dict[str, str],
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    decisions = _decisions(plan, decisions)
    source_objects = {
        data["relative_path"]: SourceFile(
            data["relative_path"], Path(data["source_path"]) if data.get("source_path") else None,
            data.get("zip_member"), int(data["size"]), data["fingerprint"],
        )
        for data in plan["files"]
    }
    total_files = len(source_objects)
    completed_files = 0
    remaining_by_source = {relative: sum(1 for item in plan["items"] if item["source_relative_path"] == relative) for relative in source_objects}

    def emit_progress(phase: str, active: list[str], *, completed: int | None = None) -> None:
        if progress is not None:
            progress({
                "phase": phase,
                "completed": completed_files if completed is None else completed,
                "total": total_files,
                "active": active,
            })

    def complete_item(item: dict[str, Any]) -> None:
        nonlocal completed_files
        relative = item["source_relative_path"]
        remaining_by_source[relative] -= 1
        if remaining_by_source[relative] == 0:
            completed_files += 1
        emit_progress("importing", [relative] if remaining_by_source[relative] else [])

    transaction = create_staging_directory(project_root / "00_Admin", ".jl-managed-import-")
    stage = transaction / "stage"
    backups = transaction / "backups"
    writes = transaction / "writes"
    applied: list[tuple[Path, Path | None]] = []
    results: list[dict[str, str]] = []
    changed_original = False
    changed_audio = False
    try:
        staged: dict[str, Path] = {}
        staged_files = 0
        for relative, source in source_objects.items():
            emit_progress("staging", [relative], completed=staged_files)
            staged[relative] = _stage_source(source, stage)
            staged_files += 1
            emit_progress("staging", [relative], completed=staged_files)
        emit_progress("importing", [])
        item_by_id = {item["id"]: item for item in plan["items"]}
        for position, item in enumerate(plan["items"]):
            relative = item["source_relative_path"]
            emit_progress("importing", [relative])
            dependency = item.get("depends_on")
            if dependency and any(result["id"] == dependency and result["result"] == "skipped" for result in results):
                results.append({"id": item["id"], "result": "skipped"})
                complete_item(item)
                continue
            if item["conflict"] and decisions.get(item["id"]) == "skip":
                results.append({"id": item["id"], "result": "skipped"})
                complete_item(item)
                continue
            destination = _managed_destination(project_root, item["destination_relative_path"])
            if _file_state(destination) != item["destination_state"]:
                raise ValidationError(f"Managed destination changed after planning: {item['destination_relative_path']}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            backup: Path | None = None
            if destination.exists():
                backup = backups / Path(item["destination_relative_path"])
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, backup)
            applied.append((destination, backup))
            if item["area"] == "audio_prep" and dependency:
                original_item = item_by_id[dependency]
                authoritative_source = _managed_destination(project_root, original_item["destination_relative_path"])
                copy_source = authoritative_source if authoritative_source.exists() else staged[item["source_relative_path"]]
            else:
                copy_source = staged[item["source_relative_path"]]
            writes.mkdir(parents=True, exist_ok=True)
            temp_dest = writes / f"write-{position}.tmp"
            shutil.copyfile(copy_source, temp_dest)
            os.replace(temp_dest, destination)
            changed_original = changed_original or item["area"] == "original_delivery"
            changed_audio = changed_audio or item["area"] == "audio_prep"
            results.append({"id": item["id"], "result": "replaced" if backup else "created"})
            complete_item(item)
        invalidated = _invalidate(project_root, changed_original, changed_audio)
        emit_progress("complete", [])
        return {"items": results, "invalidations": invalidated}
    except Exception:
        for destination, backup in reversed(applied):
            try:
                if destination.exists() and not destination.is_symlink():
                    destination.unlink()
                if backup and backup.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(backup, destination)
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(transaction, ignore_errors=True)
