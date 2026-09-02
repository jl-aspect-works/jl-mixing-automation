"""Read-side Audio Prep status built from authoritative validation facts.

This module intentionally does not perform repair/conversion. It validates the
managed Working_Audio tree against project audio policy and reports provenance
only when an unchanged working file has one unique exact-content match in
Original Delivery. Future Audio Prep mutation operations can add durable
provenance for converted/repaired outputs without changing this response shape.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .intake_incremental import validate_intake_incremental
from .os_metadata import is_ignored_os_metadata_path

_AUDIO_PREP_CACHE_NAME = "audio-prep-validation-cache.json"


def _summary(result: Any) -> dict[str, Any]:
    return {
        "files_discovered": result.files_discovered,
        "blocking_errors": result.blocking_errors,
        "warnings": result.warnings,
        "ffprobe_available": result.ffprobe_available,
        "ffmpeg_available": result.ffmpeg_available,
        "cache_reused": result.cache_reused,
        "files_validated": result.files_validated,
    }


def _originals_by_hash(original_files: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> dict[str, list[str]]:
    by_hash: dict[str, list[str]] = {}
    for record in original_files:
        sha256 = record.get("sha256")
        relative_path = record.get("relative_path")
        if isinstance(sha256, str) and sha256 and isinstance(relative_path, str) and relative_path:
            by_hash.setdefault(sha256, []).append(relative_path)
    return by_hash


def _with_provenance(record: dict[str, Any], originals: dict[str, list[str]]) -> dict[str, Any]:
    enriched = dict(record)
    sha256 = record.get("sha256")
    matches = originals.get(sha256, []) if isinstance(sha256, str) and sha256 else []
    if len(matches) == 1:
        original_path = matches[0]
        enriched["original_delivery_relative_path"] = original_path
        enriched["original_filename"] = Path(original_path).name
        enriched["provenance_state"] = "exact_content"
    elif len(matches) > 1:
        enriched["original_delivery_relative_path"] = None
        enriched["original_filename"] = None
        enriched["provenance_state"] = "ambiguous"
    else:
        enriched["original_delivery_relative_path"] = None
        enriched["original_filename"] = None
        enriched["provenance_state"] = "unavailable"
    return enriched


def build_audio_prep_status(
    project: Path,
    *,
    original_files: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    expected_sample_rate: int,
    expected_bit_depth: int,
    expected_format: str | None,
    update_cache: bool,
) -> dict[str, Any]:
    working_path = project / "02_Audio_Preparation" / "Working_Audio"
    cache_path = project / "00_Admin" / _AUDIO_PREP_CACHE_NAME

    # Project creation guarantees this directory, but older/incomplete projects
    # should degrade to an empty workspace rather than making intake validation
    # fail for an unrelated reason.
    if not working_path.is_dir() or working_path.is_symlink():
        return {
            "working_path": str(working_path),
            "validation_cache_path": str(cache_path),
            "summary": {
                "files_discovered": 0,
                "blocking_errors": 0,
                "warnings": 0,
                "ffprobe_available": None,
                "ffmpeg_available": None,
                "cache_reused": 0,
                "files_validated": 0,
            },
            "files": [],
        }

    has_files = any(
        path.is_file() and not path.is_symlink() and not is_ignored_os_metadata_path(path)
        for path in working_path.rglob("*")
    )
    if not has_files:
        return {
            "working_path": str(working_path.resolve()),
            "validation_cache_path": str(cache_path.resolve()),
            "summary": {
                "files_discovered": 0,
                "blocking_errors": 0,
                "warnings": 0,
                "ffprobe_available": None,
                "ffmpeg_available": None,
                "cache_reused": 0,
                "files_validated": 0,
            },
            "files": [],
        }

    result = validate_intake_incremental(
        working_path.resolve(),
        expected_sample_rate=expected_sample_rate,
        expected_bit_depth=expected_bit_depth,
        expected_format=expected_format,
        duplicate_check=False,
        cache_path=cache_path,
        update_cache=update_cache,
    )
    originals = _originals_by_hash(original_files)
    return {
        "working_path": str(working_path.resolve()),
        "validation_cache_path": str(cache_path.resolve()),
        "summary": _summary(result),
        "files": [_with_provenance(record, originals) for record in result.files],
    }
