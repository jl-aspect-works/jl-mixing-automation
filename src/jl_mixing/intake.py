"""Authoritative cross-platform intake-validation service."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .errors import ValidationError
from .intake_cache import cache_identity, load_cache, reusable_cache_record, sha256_file, write_cache
from .os_metadata import is_ignored_os_metadata_path

AUDIO_EXTENSIONS = {".wav", ".wave", ".aif", ".aiff", ".flac", ".mp3", ".m4a"}
_VALIDATION_WORKERS = 2
ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class IntakeResult:
    report_markdown: str
    files_discovered: int
    blocking_errors: int
    warnings: int
    ffprobe_available: bool
    ffmpeg_available: bool
    files: tuple[dict[str, Any], ...] = ()
    cache_reused: int = 0
    files_validated: int = 0

    @property
    def blocked(self) -> bool:
        return self.blocking_errors > 0


def ffprobe_metadata(path: Path, executable: str = "ffprobe") -> tuple[dict[str, Any] | None, str | None]:
    command = [
        executable, "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,bits_per_sample,bits_per_raw_sample,channels,codec_name",
        "-show_entries", "format=duration,format_name", "-of", "json", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None, result.stderr.strip() or "ffprobe could not read the file"
    try:
        payload = json.loads(result.stdout)
        stream = (payload.get("streams") or [{}])[0]
        fmt = payload.get("format") or {}
        bits = stream.get("bits_per_raw_sample") or stream.get("bits_per_sample") or None
        return {
            "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
            "bit_depth": int(bits) if bits and str(bits).isdigit() and int(bits) > 0 else None,
            "channels": int(stream["channels"]) if stream.get("channels") else None,
            "duration": float(fmt["duration"]) if fmt.get("duration") else None,
            "codec_name": stream.get("codec_name"),
            "format_name": fmt.get("format_name"),
        }, None
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return None, f"could not parse ffprobe output: {exc}"


def ffmpeg_decode_check(path: Path, executable: str = "ffmpeg") -> str | None:
    result = subprocess.run(
        [executable, "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return None
    return result.stderr.strip() or "ffmpeg could not decode the complete audio file"


def _channel_hash(path: Path, channel: int, executable: str) -> str | None:
    """Legacy single-channel helper retained for direct callers/tests."""
    result = subprocess.run(
        [
            executable, "-v", "error", "-i", str(path), "-map", "0:a:0",
            "-af", f"pan=mono|c0=c{channel}", "-f", "hash", "-hash", "sha256", "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value.split("=", 1)[1] if "=" in value else value or None


def exact_dual_mono(path: Path, metadata: dict[str, Any] | None, executable: str) -> bool | None:
    """Legacy exact comparison helper retained for direct callers/tests."""
    if not metadata or metadata.get("channels") != 2:
        return False
    left = _channel_hash(path, 0, executable)
    right = _channel_hash(path, 1, executable)
    if left is None or right is None:
        return None
    return left == right


def _parse_stereo_framehash(output: str) -> bool | None:
    streams: dict[int, list[str]] = {0: [], 1: []}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) < 6:
            continue
        try:
            stream_index = int(fields[0])
        except ValueError:
            continue
        if stream_index in streams:
            streams[stream_index].append(fields[-1])
    left = streams[0]
    right = streams[1]
    if not left or not right or len(left) != len(right):
        return None
    return left == right


def ffmpeg_decode_and_dual_mono(path: Path, executable: str = "ffmpeg") -> tuple[str | None, bool | None]:
    """Decode stereo audio once while hashing both decoded channels frame-by-frame."""
    result = subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-i",
            str(path),
            "-filter_complex",
            "[0:a:0]channelsplit=channel_layout=stereo[left][right]",
            "-map",
            "[left]",
            "-map",
            "[right]",
            "-f",
            "framehash",
            "-hash",
            "sha256",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return result.stderr.strip() or "ffmpeg could not decode the complete audio file", None
    return None, _parse_stereo_framehash(result.stdout)


def _format_technical(metadata: dict[str, Any] | None, inspection: str) -> str:
    if inspection == "unreadable":
        return "not readable"
    if inspection == "not-inspected":
        return "not inspected"
    if not metadata:
        return "readable audio"
    values: list[str] = []
    if metadata.get("sample_rate"):
        values.append(f"{metadata['sample_rate']} Hz")
    if metadata.get("bit_depth"):
        values.append(f"{metadata['bit_depth']}-bit")
    if metadata.get("channels"):
        values.append(f"{metadata['channels']} ch")
    if metadata.get("duration") is not None:
        values.append(f"{metadata['duration']:.2f} s")
    return ", ".join(values) or "readable audio"


def _items(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["- None."]


def _normalized_expected_format(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower().lstrip(".")
    aliases = {"wave": "wav", "aif": "aiff"}
    return aliases.get(normalized, normalized)


def _actual_format(path: Path) -> str | None:
    extension = path.suffix.lower().lstrip(".")
    if not extension:
        return None
    return {"wave": "wav", "aif": "aiff"}.get(extension, extension)


def _finding(
    code: str,
    severity: str,
    message: str,
    *,
    expected: Any | None = None,
    actual: Any | None = None,
    related_paths: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if expected is not None:
        result["expected"] = expected
    if actual is not None:
        result["actual"] = actual
    if related_paths:
        result["related_paths"] = related_paths
    return result


def _status_for(record: dict[str, Any]) -> str:
    if not record.get("is_audio"):
        return "not_applicable"
    severities = {finding.get("severity") for finding in record.get("findings", [])}
    if "critical" in severities:
        return "blocked"
    if "warning" in severities:
        return "needs_attention"
    if "info" in severities:
        return "info"
    return "valid"


def _without_duplicate_findings(record: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(record)
    findings = cleaned.get("findings")
    if isinstance(findings, list):
        cleaned["findings"] = [
            finding
            for finding in findings
            if not isinstance(finding, dict) or finding.get("code") != "EXACT_DUPLICATE"
        ]
    return cleaned


def validate_intake(
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
    source = source.resolve()
    if not source.is_dir() or source.is_symlink():
        raise ValidationError(f"Source directory not found or unsafe: {source}")

    if progress is not None:
        progress({"phase": "scanning", "completed": 0, "total": None, "active": []})
    files = sorted(
        (
            p
            for p in source.rglob("*")
            if p.is_file() and not p.is_symlink() and not is_ignored_os_metadata_path(p)
        ),
        key=lambda p: str(p.relative_to(source)).lower(),
    )
    detected_ffprobe = ffprobe_path if ffprobe_path is not None else shutil.which("ffprobe")
    detected_ffmpeg = ffmpeg_path if ffmpeg_path is not None else shutil.which("ffmpeg")
    ffprobe_available = bool(detected_ffprobe)
    ffmpeg_available = bool(detected_ffmpeg)
    expected_file_format = _normalized_expected_format(expected_format)
    prior_cache = load_cache(cache_path)
    next_cache: dict[str, dict[str, Any]] = {}

    critical_errors: list[str] = []
    duplicate_findings: list[str] = []
    mismatch_findings: list[str] = []
    channel_findings: list[str] = []
    unsupported_findings: list[str] = []
    unavailable_findings: list[str] = []
    inventory: list[tuple[Path, dict[str, Any] | None, str]] = []
    results_by_path: dict[str, dict[str, Any]] = {}
    cache_reused = 0
    files_validated = 0
    total_files = len(files)
    completed_files = 0
    active_files: set[str] = set()
    progress_lock = threading.Lock()

    def emit_progress(phase: str = "validating") -> None:
        if progress is None:
            return
        progress({
            "phase": phase,
            "completed": completed_files,
            "total": total_files,
            "active": sorted(active_files, key=str.lower),
        })

    if not files:
        critical_errors.append("No files were found in the intake source.")
    emit_progress()

    uncached: list[tuple[Path, str, bool]] = []
    for path in files:
        relative = str(path.relative_to(source)).replace("\\", "/")
        is_audio = path.suffix.lower() in AUDIO_EXTENSIONS
        reusable = reusable_cache_record(path, relative, prior_cache)
        if reusable is not None and reusable.get("is_audio") == is_audio:
            record = _without_duplicate_findings(reusable)
            record["cache_state"] = "reused"
            results_by_path[relative] = record
            cache_reused += 1
            completed_files += 1
            emit_progress()
        else:
            uncached.append((path, relative, is_audio))

    def validate_file(item: tuple[Path, str, bool]) -> tuple[str, dict[str, Any]]:
        path, relative, is_audio = item
        nonlocal completed_files
        with progress_lock:
            active_files.add(relative)
            emit_progress()
        try:
            metadata: dict[str, Any] | None = None
            inspection = "not-inspected"
            findings: list[dict[str, Any]] = []
            decode_ok: bool | None = None
            dual_mono: bool | None = None
            digest: str | None = None

            if is_audio:
                digest = sha256_file(path)
                if ffprobe_available:
                    metadata, probe_error = ffprobe_metadata(path, str(detected_ffprobe))
                    if probe_error:
                        inspection = "unreadable"
                        findings.append(_finding(
                            "FFPROBE_UNREADABLE", "critical",
                            f"ffprobe could not inspect the audio file: {probe_error}",
                        ))
                    else:
                        inspection = "inspected"
                else:
                    findings.append(_finding(
                        "FFPROBE_UNAVAILABLE", "warning",
                        "ffprobe is unavailable; technical metadata could not be inspected.",
                    ))

                if ffmpeg_available:
                    if metadata and metadata.get("channels") == 2:
                        decode_error, dual_mono = ffmpeg_decode_and_dual_mono(
                            path, str(detected_ffmpeg)
                        )
                    else:
                        decode_error = ffmpeg_decode_check(path, str(detected_ffmpeg))
                    decode_ok = decode_error is None
                    if decode_error:
                        findings.append(_finding(
                            "DECODE_INTEGRITY_FAILED", "critical",
                            f"Full-file decode integrity check failed: {decode_error}",
                        ))
                    elif dual_mono:
                        findings.append(_finding(
                            "EXACT_DUAL_MONO", "info",
                            "Stereo left and right channels are exactly identical.",
                        ))
                else:
                    findings.append(_finding(
                        "FFMPEG_UNAVAILABLE", "warning",
                        "ffmpeg is unavailable; full-file decode integrity could not be checked.",
                    ))

                if metadata:
                    rate = metadata.get("sample_rate")
                    depth = metadata.get("bit_depth")
                    if expected_sample_rate and rate and rate != expected_sample_rate:
                        findings.append(_finding(
                            "SAMPLE_RATE_MISMATCH", "warning",
                            f"Sample rate is {rate} Hz; expected {expected_sample_rate} Hz.",
                            expected=expected_sample_rate, actual=rate,
                        ))
                    if expected_bit_depth and depth and depth != expected_bit_depth:
                        findings.append(_finding(
                            "BIT_DEPTH_MISMATCH", "warning",
                            f"Bit depth is {depth}-bit; expected {expected_bit_depth}-bit.",
                            expected=expected_bit_depth, actual=depth,
                        ))
                actual_format = _actual_format(path)
                if expected_file_format and actual_format and actual_format != expected_file_format:
                    findings.append(_finding(
                        "FILE_FORMAT_MISMATCH", "warning",
                        f"File format is {actual_format.upper()}; expected {expected_file_format.upper()}.",
                        expected=expected_file_format.upper(), actual=actual_format.upper(),
                    ))

            record = {
                **cache_identity(path),
                "relative_path": relative,
                "is_audio": is_audio,
                "sha256": digest,
                "metadata": metadata,
                "inspection": inspection,
                "decode_ok": decode_ok,
                "dual_mono": dual_mono,
                "findings": findings,
                "cache_state": "validated",
            }
            return relative, record
        finally:
            with progress_lock:
                active_files.discard(relative)
                completed_files += 1
                emit_progress()

    if uncached:
        with ThreadPoolExecutor(max_workers=_VALIDATION_WORKERS, thread_name_prefix="intake") as executor:
            for relative, record in executor.map(validate_file, uncached):
                results_by_path[relative] = record
        files_validated = len(uncached)

    file_results: list[dict[str, Any]] = []
    for path in files:
        relative = str(path.relative_to(source)).replace("\\", "/")
        record = results_by_path[relative]
        record["relative_path"] = relative
        record["status"] = _status_for(record)
        file_results.append(record)

    if duplicate_check:
        by_hash: dict[str, list[dict[str, Any]]] = {}
        for record in file_results:
            digest = record.get("sha256")
            if record.get("is_audio") and isinstance(digest, str) and digest:
                by_hash.setdefault(digest, []).append(record)
        for group in by_hash.values():
            if len(group) < 2:
                continue
            paths = [str(record["relative_path"]) for record in group]
            duplicate_findings.append(", ".join(f"`{value}`" for value in paths))
            for record in group:
                others = [value for value in paths if value != record["relative_path"]]
                record.setdefault("findings", []).append(_finding(
                    "EXACT_DUPLICATE", "info", "Exact duplicate audio content detected.",
                    related_paths=others,
                ))
                record["status"] = _status_for(record)
    else:
        unavailable_findings.append("Exact duplicate-content detection was skipped.")

    for record in file_results:
        relative = str(record["relative_path"])
        next_cache[relative] = {
            key: value for key, value in record.items() if key not in {"cache_state", "status"}
        }
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else None
        inspection = str(record.get("inspection") or "not-inspected")
        path = source / Path(relative)
        inventory.append((path, metadata, inspection))
        if not record.get("is_audio"):
            unsupported_findings.append(f"`{relative}`")
        for finding in record.get("findings", []):
            severity = finding.get("severity")
            code = finding.get("code")
            message = str(finding.get("message") or "")
            if severity == "critical":
                critical_errors.append(f"`{relative}`: {message}")
            elif code in {"SAMPLE_RATE_MISMATCH", "BIT_DEPTH_MISMATCH", "FILE_FORMAT_MISMATCH"}:
                mismatch_findings.append(f"`{relative}`: {message}")
            elif code == "EXACT_DUAL_MONO":
                channel_findings.append(f"`{relative}`: {message}")

    if not ffprobe_available:
        unavailable_findings.append("ffprobe is not installed; enhanced audio metadata inspection was unavailable.")
    if not ffmpeg_available:
        unavailable_findings.append("ffmpeg is not installed; decode integrity and dual-mono checks were unavailable.")

    warning_count = (
        len(duplicate_findings)
        + len(mismatch_findings)
        + len(channel_findings)
        + len(unsupported_findings)
        + len(unavailable_findings)
    )
    enhanced = "available through ffprobe" if ffprobe_available else "unavailable"
    lines = [
        "## Intake Summary", "", f"- Source: `{source}`", f"- Files discovered: {len(files)}",
        f"- Blocking errors: {len(critical_errors)}", f"- Warnings: {warning_count}",
        f"- Cache reused: {cache_reused}", f"- Files validated: {files_validated}",
        f"- Expected sample rate: {expected_sample_rate or 'not specified'}",
        f"- Expected bit depth: {expected_bit_depth or 'not specified'}",
        f"- Expected file format: {expected_file_format.upper() if expected_file_format else 'not specified'}",
        f"- Enhanced inspection: {enhanced}", "", "## Critical Errors", "",
    ]
    lines.extend(_items(critical_errors))
    for title, items in (
        ("Exact Duplicate Files", duplicate_findings),
        ("Project-Format Mismatches", mismatch_findings),
        ("Channel Warnings", channel_findings),
        ("Unsupported or Non-Audio Files", unsupported_findings),
        ("Skipped or Unavailable Checks", unavailable_findings),
    ):
        lines.extend(["", f"## {title}", ""])
        lines.extend(_items(items))
    lines.extend(["", "## Source Inventory", "", "| File | Size (bytes) | Technical details | Status |", "|---|---:|---|---|"])
    status_by_path = {str(record["relative_path"]): str(record["status"]) for record in file_results}
    for path, metadata, inspection in inventory:
        relative = str(path.relative_to(source)).replace("|", "\\|").replace("\\", "/")
        status = status_by_path.get(str(path.relative_to(source)).replace("\\", "/"), "not_applicable")
        lines.append(
            f"| `{relative}` | {path.stat().st_size} | {_format_technical(metadata, inspection)} | {status} |"
        )
    if not inventory:
        lines.append("| _No files_ | 0 | — | — |")

    recommendations: list[str] = []
    if critical_errors:
        recommendations.append("Resolve blocking errors before preparing `Working_Audio/`.")
    if mismatch_findings:
        recommendations.append("Review project-format mismatches before conversion or DAW import.")
    if duplicate_findings:
        recommendations.append("Review exact duplicate files before DAW import.")
    if channel_findings:
        recommendations.append("Review exact dual-mono files and confirm intended channel handling.")
    if unsupported_findings:
        recommendations.append("Review unsupported or non-audio files and retain any required documentation.")
    if unavailable_findings:
        recommendations.append("Document skipped or unavailable checks in `Preparation_Report.md`.")
    if not recommendations:
        recommendations.append("Intake is ready for manual audio preparation.")
    lines.extend(["", "## Preparation Recommendations", ""])
    lines.extend(f"- {item}" for item in recommendations)

    if update_cache:
        try:
            write_cache(cache_path, next_cache)
        except OSError as exc:
            raise ValidationError(f"Unable to update intake validation cache: {cache_path}") from exc

    emit_progress("complete")
    return IntakeResult(
        report_markdown="\n".join(lines).rstrip() + "\n",
        files_discovered=len(files),
        blocking_errors=len(critical_errors),
        warnings=warning_count,
        ffprobe_available=ffprobe_available,
        ffmpeg_available=ffmpeg_available,
        files=tuple(file_results),
        cache_reused=cache_reused,
        files_validated=files_validated,
    )