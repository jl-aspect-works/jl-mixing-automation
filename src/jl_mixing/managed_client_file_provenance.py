"""Persistent provenance for managed Original Delivery -> Audio Prep lineage.

Source identity is the Original Delivery relative path. Content hashes are evidence used
for migration/recovery only, not identity: working audio may be renamed, repaired, or
converted while retaining the same lineage. Future repair operations should preserve the
working path entry (or update it if they move/replace the working file) and may append to
``transformations`` without changing ``source_relative_path``.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from . import diagnostic_log
from .errors import UnsafeOperationError, ValidationError
from . import managed_client_files as base
from .filesystem_noise import is_filesystem_noise_name

PROVENANCE_PATH = Path("00_Admin") / "audio-prep-provenance.json"
SCHEMA_VERSION = 1


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def _empty_document() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "entries": []}


def _load(project_root: Path) -> dict[str, Any]:
    path = project_root / PROVENANCE_PATH
    if not path.exists():
        return _empty_document()
    if path.is_symlink() or not path.is_file():
        raise UnsafeOperationError(f"Audio Prep provenance path is unavailable or unsafe: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Audio Prep provenance is unreadable: {path}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION or not isinstance(document.get("entries"), list):
        raise ValidationError("Audio Prep provenance has an unsupported format; repair is required.")

    seen_sources: set[str] = set()
    seen_working: set[str] = set()
    for entry in document["entries"]:
        if not isinstance(entry, dict):
            raise ValidationError("Audio Prep provenance contains an invalid entry; repair is required.")
        source = base._safe_relative(str(entry.get("source_relative_path", "")))
        working = base._safe_relative(str(entry.get("working_relative_path", "")))
        if not working.startswith(f"{base.AUDIO_ROOT.as_posix()}/"):
            raise ValidationError("Audio Prep provenance points outside Working_Audio; repair is required.")
        source_key = source.casefold()
        working_key = working.casefold()
        if source_key in seen_sources or working_key in seen_working:
            raise ValidationError("Audio Prep provenance contains ambiguous lineage; repair is required.")
        seen_sources.add(source_key)
        seen_working.add(working_key)
    return document


def _write(project_root: Path, document: dict[str, Any]) -> None:
    path = project_root / PROVENANCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise UnsafeOperationError(f"Audio Prep provenance path may not be a symlink: {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _source_objects(plan: dict[str, Any]) -> list[base.SourceFile]:
    return [
        base.SourceFile(
            data["relative_path"],
            Path(data["source_path"]) if data.get("source_path") else None,
            data.get("zip_member"),
            int(data["size"]),
            data["fingerprint"],
        )
        for data in plan["files"]
    ]


class _WorkingHashIndex:
    """Lazy per-plan Working_Audio content index.

    Direct provenance hits need no content scan. The first recovery/fallback lookup
    hashes each safe working file exactly once and subsequent lookups reuse the map.
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._by_hash: dict[str, list[str]] | None = None

    def _build(self) -> dict[str, list[str]]:
        started = time.perf_counter()
        audio_root = self.project_root / base.AUDIO_ROOT
        if not audio_root.exists():
            diagnostic_log.info(
                "managed_import_working_hash_index_profile",
                file_count=0,
                total_bytes=0,
                elapsed_ms=_elapsed_ms(started),
            )
            return {}
        if audio_root.is_symlink() or not audio_root.is_dir():
            raise UnsafeOperationError(f"Audio Prep root is unavailable or unsafe: {audio_root}")
        by_hash: dict[str, list[str]] = {}
        file_count = 0
        total_bytes = 0
        for current, dirs, names in os.walk(audio_root, followlinks=False):
            current_path = Path(current)
            for directory in dirs:
                if (current_path / directory).is_symlink():
                    raise UnsafeOperationError(f"Audio Prep does not allow symlink traversal: {current_path / directory}")
            for name in names:
                candidate = current_path / name
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                if is_filesystem_noise_name(name):
                    continue
                size = candidate.stat().st_size
                hash_started = time.perf_counter()
                digest = base._sha256_file(candidate)
                diagnostic_log.debug(
                    "managed_import_working_hash_file_profile",
                    size_bytes=size,
                    elapsed_ms=_elapsed_ms(hash_started),
                )
                relative = (base.AUDIO_ROOT / candidate.relative_to(audio_root)).as_posix()
                by_hash.setdefault(digest, []).append(relative)
                file_count += 1
                total_bytes += size
        diagnostic_log.info(
            "managed_import_working_hash_index_profile",
            file_count=file_count,
            total_bytes=total_bytes,
            elapsed_ms=_elapsed_ms(started),
        )
        return by_hash

    def match(self, digest: str, *, ambiguity_message: str) -> str | None:
        if self._by_hash is None:
            self._by_hash = self._build()
        matches = self._by_hash.get(digest, [])
        if len(matches) > 1:
            raise ValidationError(ambiguity_message)
        return matches[0] if matches else None


def _provenance_by_source(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(entry["source_relative_path"]).casefold(): entry for entry in document["entries"]}


def _lineage_destination(project_root: Path, source_relative: str, provenance: dict[str, dict[str, Any]], working_index: _WorkingHashIndex) -> str | None:
    entry = provenance.get(source_relative.casefold())
    if entry is None:
        return None
    working = base._safe_relative(str(entry["working_relative_path"]))
    destination = base._managed_destination(project_root, working)
    if destination.is_file():
        return working
    recorded_hash = entry.get("working_sha256")
    if isinstance(recorded_hash, str) and recorded_hash:
        return working_index.match(recorded_hash, ambiguity_message="Multiple Audio Prep files match recorded working-file provenance; repair is required.")
    return None


def _fallback_match(source_relative: str, candidate: Path | None, working_index: _WorkingHashIndex) -> str | None:
    if candidate is None or not candidate.is_file():
        return None
    size = candidate.stat().st_size
    started = time.perf_counter()
    source_hash = base._sha256_file(candidate)
    diagnostic_log.debug(
        "managed_import_fallback_hash_profile",
        source_relative_path=source_relative,
        size_bytes=size,
        elapsed_ms=_elapsed_ms(started),
    )
    return working_index.match(source_hash, ambiguity_message=f"Multiple Audio Prep files match Original Delivery content for {source_relative}; repair is required before reset.")


def _resolved_destination(project_root: Path, source_relative: str, fallback_source: Path | None, provenance: dict[str, dict[str, Any]], working_index: _WorkingHashIndex) -> str | None:
    return _lineage_destination(project_root, source_relative, provenance, working_index) or _fallback_match(source_relative, fallback_source, working_index)


def plan_import(
    project_root: Path,
    source_kind: str,
    sources: tuple[Path, ...],
    *,
    progress: base.ProgressCallback | None = None,
) -> dict[str, Any]:
    total_started = time.perf_counter()
    base_started = time.perf_counter()
    base_progress = None
    if progress is not None:
        def base_progress(event: dict[str, Any]) -> None:
            completed = int(event.get("completed", 0))
            total = int(event.get("total", 0))
            progress({**event, "completed": completed, "total": total * 2})
    plan = base.plan_import(project_root, source_kind, sources, progress=base_progress)
    base_plan_ms = _elapsed_ms(base_started)

    provenance_started = time.perf_counter()
    source_objects = {source.relative_path: source for source in _source_objects(plan)}
    provenance = _provenance_by_source(_load(project_root))
    provenance_load_ms = _elapsed_ms(provenance_started)

    resolution_started = time.perf_counter()
    working_index = _WorkingHashIndex(project_root)
    items: list[dict[str, Any]] = []
    resolved_count = 0
    total_sources = len(source_objects)
    for item in plan["items"]:
        if item["area"] != "audio_prep":
            items.append(item)
            continue
        source_relative = item["source_relative_path"]
        source = source_objects[source_relative]
        existing_original = base._managed_destination(project_root, (base.ORIGINAL_ROOT / Path(source_relative)).as_posix())
        fallback = existing_original if existing_original.is_file() else (None if source.zip_member is not None else source.source_path)
        destination = _resolved_destination(project_root, source_relative, fallback, provenance, working_index)
        if destination:
            items.append(base._item(project_root, item["id"], "audio_prep", destination, source, depends_on=item.get("depends_on")))
        else:
            items.append(item)
        resolved_count += 1
        if progress is not None:
            progress({"phase": "planning", "completed": total_sources + resolved_count, "total": total_sources * 2, "active": [source_relative]})
    resolution_ms = _elapsed_ms(resolution_started)

    finalize_started = time.perf_counter()
    plan["items"] = items
    plan["plan_id"] = base._plan_id("client.files.import", source_kind, sources, source_objects.values(), items)
    finalize_ms = _elapsed_ms(finalize_started)
    diagnostic_log.info(
        "managed_import_provenance_plan_profile",
        source_kind=source_kind,
        file_count=len(source_objects),
        provenance_entry_count=len(provenance),
        base_plan_ms=base_plan_ms,
        provenance_load_ms=provenance_load_ms,
        resolution_ms=resolution_ms,
        finalize_ms=finalize_ms,
        total_ms=_elapsed_ms(total_started),
    )
    return plan


def plan_reset(project_root: Path, relative_paths: tuple[str, ...]) -> dict[str, Any]:
    files: list[base.SourceFile] = []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    provenance = _provenance_by_source(_load(project_root))
    working_index = _WorkingHashIndex(project_root)
    for index, raw in enumerate(relative_paths):
        relative = base._safe_relative(raw)
        key = relative.casefold()
        if key in seen:
            raise ValidationError(f"Duplicate reset path: {relative}")
        seen.add(key)
        source = base._managed_destination(project_root, (base.ORIGINAL_ROOT / Path(relative)).as_posix())
        if not source.is_file():
            raise ValidationError(f"Original Delivery file not found: {relative}")
        source_file = base.SourceFile(relative, source, None, source.stat().st_size, base._source_fingerprint(source))
        files.append(source_file)
        destination = _resolved_destination(project_root, relative, source, provenance, working_index) or (base.AUDIO_ROOT / Path(relative)).as_posix()
        items.append(base._item(project_root, f"audio:{index}", "audio_prep", destination, source_file))
    if not files:
        raise ValidationError("At least one Original Delivery file is required.")
    return {
        "operation": "audio.prep.reset",
        "source_kind": "original_delivery",
        "sources": [source.relative_path for source in files],
        "plan_id": base._plan_id("audio.prep.reset", "original_delivery", (), files, items),
        "files": [base._serialized_source(source) for source in files],
        "items": items,
    }


def _record_successful_lineage(
    project_root: Path,
    plan: dict[str, Any],
    result: dict[str, Any],
    content_hashes: dict[str, str] | None = None,
    *,
    progress: base.ProgressCallback | None = None,
) -> None:
    total_started = time.perf_counter()
    statuses = {item["id"]: item["result"] for item in result.get("items", [])}
    load_started = time.perf_counter()
    document = _load(project_root)
    load_ms = _elapsed_ms(load_started)
    entries = list(document["entries"])
    changed = False
    source_hash_ms = 0.0
    working_hash_ms = 0.0
    hashed_bytes = 0
    reused_hash_count = 0
    reused_hash_bytes = 0
    recorded_count = 0
    eligible_items = [item for item in plan["items"] if item["area"] == "audio_prep" and statuses.get(item["id"]) in {"created", "replaced"}]
    total_eligible = len(eligible_items)
    for item in eligible_items:
        source_relative = base._safe_relative(item["source_relative_path"])
        working_relative = base._safe_relative(item["destination_relative_path"])
        reusable_hash = content_hashes.get(source_relative) if content_hashes is not None else None
        if reusable_hash:
            source_size = int(item["size_bytes"])
            working_size = source_size
        else:
            source_path = base._managed_destination(project_root, (base.ORIGINAL_ROOT / Path(source_relative)).as_posix())
            working_path = base._managed_destination(project_root, working_relative)
            if not source_path.is_file() or not working_path.is_file():
                continue
            source_size = source_path.stat().st_size
            working_size = working_path.stat().st_size
        if reusable_hash:
            source_hash = reusable_hash
            working_hash = reusable_hash
            source_elapsed = 0.0
            working_elapsed = 0.0
            reused_hash_count += 1
            reused_hash_bytes += source_size + working_size
        else:
            source_started = time.perf_counter()
            source_hash = base._sha256_file(source_path)
            source_elapsed = _elapsed_ms(source_started)
            source_hash_ms += source_elapsed
            working_started = time.perf_counter()
            working_hash = base._sha256_file(working_path)
            working_elapsed = _elapsed_ms(working_started)
            working_hash_ms += working_elapsed
            hashed_bytes += source_size + working_size
        diagnostic_log.debug(
            "managed_import_provenance_hash_file_profile",
            source_relative_path=source_relative,
            source_size_bytes=source_size,
            working_size_bytes=working_size,
            source_hash_ms=source_elapsed,
            working_hash_ms=working_elapsed,
            reused_staged_hash=bool(reusable_hash),
        )
        source_key = source_relative.casefold()
        working_key = working_relative.casefold()
        entries = [entry for entry in entries if str(entry.get("source_relative_path", "")).casefold() != source_key and str(entry.get("working_relative_path", "")).casefold() != working_key]
        entries.append({
            "source_relative_path": source_relative,
            "working_relative_path": working_relative,
            "source_sha256": source_hash,
            "working_sha256": working_hash,
            "transformations": ["copied"],
        })
        recorded_count += 1
        changed = True
        if progress is not None:
            progress({"phase": "finalizing", "completed": recorded_count, "total": total_eligible, "active": [source_relative]})
    write_ms = 0.0
    if changed:
        entries.sort(key=lambda entry: str(entry["source_relative_path"]).casefold())
        document["entries"] = entries
        write_started = time.perf_counter()
        _write(project_root, document)
        write_ms = _elapsed_ms(write_started)
    diagnostic_log.info(
        "managed_import_provenance_finalize_profile",
        recorded_count=recorded_count,
        hashed_bytes=hashed_bytes,
        reused_hash_count=reused_hash_count,
        reused_hash_bytes=reused_hash_bytes,
        load_ms=load_ms,
        source_hash_ms=round(source_hash_ms, 3),
        working_hash_ms=round(working_hash_ms, 3),
        write_ms=write_ms,
        total_ms=_elapsed_ms(total_started),
    )


def execute_plan(
    project_root: Path,
    plan: dict[str, Any],
    decisions: dict[str, str],
    *,
    progress: base.ProgressCallback | None = None,
) -> dict[str, Any]:
    total_started = time.perf_counter()
    base_started = time.perf_counter()
    content_hashes: dict[str, str] = {}
    def base_progress(event: dict[str, Any]) -> None:
        if progress is not None and event.get("phase") != "complete":
            progress(event)

    result = base.execute_plan(project_root, plan, decisions, progress=base_progress if progress is not None else None, content_hashes=content_hashes)
    base_execute_ms = _elapsed_ms(base_started)
    lineage_started = time.perf_counter()
    _record_successful_lineage(project_root, plan, result, content_hashes, progress=progress)
    lineage_ms = _elapsed_ms(lineage_started)
    if progress is not None:
        total_files = len(plan.get("files", []))
        progress({"phase": "complete", "completed": total_files, "total": total_files, "active": []})
    diagnostic_log.info(
        "managed_import_provenance_execute_profile",
        base_execute_ms=base_execute_ms,
        lineage_ms=lineage_ms,
        total_ms=_elapsed_ms(total_started),
    )
    return result
