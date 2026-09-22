"""Incremental intake-validation coordinator.

The low-level intake service caches expensive file inspection facts. This layer
ensures those cached facts are reused only under the same project validation
context, so changes to expected format or tool capability cannot return stale
findings.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

from .intake import IntakeResult, ProgressCallback, validate_intake


def _normalized_format(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower().lstrip(".")
    return {"wave": "wav", "aif": "aiff"}.get(normalized, normalized)


def _tool_value(explicit: str | None, executable: str) -> str | None:
    if explicit is not None:
        return explicit or None
    return shutil.which(executable)


def _context(
    *,
    expected_sample_rate: int | None,
    expected_bit_depth: int | None,
    expected_format: str | None,
    ffprobe_path: str | None,
    ffmpeg_path: str | None,
) -> dict[str, Any]:
    return {
        "expected_sample_rate": expected_sample_rate,
        "expected_bit_depth": expected_bit_depth,
        "expected_format": _normalized_format(expected_format),
        "ffprobe_available": bool(ffprobe_path),
        "ffmpeg_available": bool(ffmpeg_path),
    }


def _read_context(cache_path: Path) -> dict[str, Any] | None:
    if not cache_path.is_file() or cache_path.is_symlink():
        return None
    try:
        document = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    context = document.get("validation_context") if isinstance(document, dict) else None
    return context if isinstance(context, dict) else None


def _annotate_cache(cache_path: Path, context: dict[str, Any]) -> None:
    document = json.loads(cache_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return
    document["validation_context"] = context
    temporary = cache_path.with_name(f".{cache_path.name}.{os.getpid()}.context.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(cache_path)


def _duplicate_basenames(result: IntakeResult) -> list[str]:
    by_name: dict[str, list[str]] = {}
    for record in result.files:
        relative = record.get("relative_path")
        if not isinstance(relative, str) or not relative:
            continue
        by_name.setdefault(Path(relative).name.lower(), []).append(relative)
    return [
        ", ".join(f"`{relative}`" for relative in relatives)
        for relatives in by_name.values()
        if len(relatives) > 1
    ]


def _legacy_warning_count(result: IntakeResult, duplicate_findings: list[str]) -> int:
    mismatch_codes = {"SAMPLE_RATE_MISMATCH", "BIT_DEPTH_MISMATCH", "FILE_FORMAT_MISMATCH"}
    mismatch_count = 0
    unsupported_count = 0
    for record in result.files:
        if not record.get("is_audio"):
            unsupported_count += 1
        for finding in record.get("findings", []):
            if isinstance(finding, dict) and finding.get("code") in mismatch_codes:
                mismatch_count += 1
    return (
        len(duplicate_findings)
        + mismatch_count
        + unsupported_count
        + (0 if result.ffprobe_available else 1)
    )


def _preserve_human_report_compatibility(
    result: IntakeResult,
    *,
    duplicate_check: bool,
) -> IntakeResult:
    report = result.report_markdown
    for record in result.files:
        relative = record.get("relative_path")
        if not isinstance(relative, str):
            continue
        for finding in record.get("findings", []):
            if not isinstance(finding, dict):
                continue
            code = finding.get("code")
            message = str(finding.get("message") or "")
            generic = f"- `{relative}`: {message}"
            compatible: str | None = None
            if code == "FFPROBE_UNREADABLE":
                detail = message.removeprefix("ffprobe could not inspect the audio file: ")
                compatible = f"- Unreadable audio file `{relative}`: {detail}"
            elif code == "SAMPLE_RATE_MISMATCH":
                actual = finding.get("actual")
                expected = finding.get("expected")
                if actual is not None and expected is not None:
                    compatible = f"- `{relative}`: {actual} Hz; expected {expected} Hz."
            elif code == "BIT_DEPTH_MISMATCH":
                actual = finding.get("actual")
                expected = finding.get("expected")
                if actual is not None and expected is not None:
                    compatible = f"- `{relative}`: {actual}-bit; expected {expected}-bit."
            if compatible is not None:
                report = report.replace(generic, compatible)

    duplicate_findings = _duplicate_basenames(result) if duplicate_check else []
    duplicate_lines = "\n".join(f"- {item}" for item in duplicate_findings) or "- None."
    legacy_section = f"## Duplicate Filenames\n\n{duplicate_lines}\n\n"
    marker = "## Exact Duplicate Files"
    if marker in report and "## Duplicate Filenames" not in report:
        report = report.replace(marker, legacy_section + marker, 1)

    if not duplicate_check:
        report = report.replace(
            "Exact duplicate-content detection was skipped.",
            "Duplicate-basename detection was skipped. Exact duplicate-content detection was skipped.",
        )

    if duplicate_findings:
        recommendation_marker = "## Preparation Recommendations\n\n"
        legacy_recommendation = "- Review duplicate filenames to avoid ambiguous DAW imports.\n"
        if recommendation_marker in report and legacy_recommendation not in report:
            report = report.replace(
                recommendation_marker,
                recommendation_marker + legacy_recommendation,
                1,
            )

    warning_count = _legacy_warning_count(result, duplicate_findings)
    report_lines = report.splitlines()
    for index, line in enumerate(report_lines):
        if line.startswith("- Warnings: "):
            report_lines[index] = f"- Warnings: {warning_count}"
            break
    report = "\n".join(report_lines).rstrip() + "\n"
    return replace(result, report_markdown=report, warnings=warning_count)


def validate_intake_incremental(
    source: Path,
    *,
    expected_sample_rate: int | None = None,
    expected_bit_depth: int | None = None,
    expected_format: str | None = None,
    duplicate_check: bool = True,
    ffprobe_path: str | None = None,
    ffmpeg_path: str | None = None,
    cache_path: Path | None = None,
    update_cache: bool = True,
    progress: ProgressCallback | None = None,
) -> IntakeResult:
    resolved_ffprobe = _tool_value(ffprobe_path, "ffprobe")
    resolved_ffmpeg = _tool_value(ffmpeg_path, "ffmpeg")
    context = _context(
        expected_sample_rate=expected_sample_rate,
        expected_bit_depth=expected_bit_depth,
        expected_format=expected_format,
        ffprobe_path=resolved_ffprobe,
        ffmpeg_path=resolved_ffmpeg,
    )

    active_cache = cache_path
    temporary_cache: Path | None = None
    if cache_path is not None and _read_context(cache_path) != context:
        if update_cache:
            temporary_cache = cache_path.with_name(f".{cache_path.name}.{os.getpid()}.refresh.tmp")
            try:
                temporary_cache.unlink()
            except FileNotFoundError:
                pass
            active_cache = temporary_cache
        else:
            active_cache = None

    result = validate_intake(
        source,
        expected_sample_rate=expected_sample_rate,
        expected_bit_depth=expected_bit_depth,
        expected_format=expected_format,
        duplicate_check=duplicate_check,
        ffprobe_path=resolved_ffprobe or "",
        ffmpeg_path=resolved_ffmpeg or "",
        cache_path=active_cache,
        update_cache=update_cache,
        progress=progress,
    )
    result = _preserve_human_report_compatibility(result, duplicate_check=duplicate_check)

    if update_cache and active_cache is not None and active_cache.is_file():
        _annotate_cache(active_cache, context)
        if temporary_cache is not None and cache_path is not None:
            temporary_cache.replace(cache_path)

    return result