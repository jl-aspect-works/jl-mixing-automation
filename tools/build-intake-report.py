#!/usr/bin/env python3
"""Build the automation-managed section of ``Intake_Report.md``.

The shell command ``validate-intake`` owns v1.1 project/context validation and
managed-section replacement. This helper intentionally preserves the exact
v1.0.4 intake checks: recursive regular-file inventory, duplicate-basename
warnings, extension-based audio candidacy, opportunistic ``ffprobe`` metadata,
project sample-rate/bit-depth comparisons, and unreadable candidate-audio
errors. It does not add broader audio QC.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

# Preserve the v1.0.4 audio-candidate allowlist exactly. Files outside this set
# remain visible in the inventory and are reported as unsupported/non-audio.
AUDIO_EXTENSIONS = {".wav", ".wave", ".aif", ".aiff", ".flac", ".mp3", ".m4a"}


def parse_args() -> argparse.Namespace:
    """Parse the narrow private interface used by the Bash wrapper and tests."""

    parser = argparse.ArgumentParser(
        description="Generate the managed intake-validation Markdown section."
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--expected-sample-rate", type=int)
    parser.add_argument("--expected-bit-depth", type=int)
    parser.add_argument("--no-duplicate-check", action="store_true")
    return parser.parse_args()


def ffprobe_metadata(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Inspect the first audio stream using the preserved v1.0.4 probe fields."""

    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate,bits_per_sample,bits_per_raw_sample,channels",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = result.stderr.strip() or "ffprobe could not read the file"
        return None, message

    try:
        payload = json.loads(result.stdout)
        stream = (payload.get("streams") or [{}])[0]
        fmt = payload.get("format") or {}
        bits = stream.get("bits_per_raw_sample") or stream.get("bits_per_sample") or None
        return (
            {
                "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
                "bit_depth": int(bits) if bits and str(bits).isdigit() and int(bits) > 0 else None,
                "channels": int(stream["channels"]) if stream.get("channels") else None,
                "duration": float(fmt["duration"]) if fmt.get("duration") else None,
            },
            None,
        )
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return None, f"could not parse ffprobe output: {exc}"


def format_technical(metadata: dict[str, Any] | None, inspection: str) -> str:
    """Format the existing opportunistic metadata for one inventory row."""

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


def markdown_items(items: list[str]) -> list[str]:
    """Render a stable bullet list, using an explicit empty-state entry."""

    return [f"- {item}" for item in items] if items else ["- None."]


def write_summary(
    path: Path | None,
    *,
    file_count: int,
    error_count: int,
    warning_count: int,
    ffprobe_available: bool,
) -> None:
    """Write the private command-summary JSON when requested."""

    if path is None:
        return
    payload = {
        "files_discovered": file_count,
        "blocking_errors": error_count,
        "warnings": warning_count,
        "ffprobe_available": ffprobe_available,
    }
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    """Inventory the source, render clearer Markdown, and return v1.0.4 status."""

    args = parse_args()
    source = args.source.resolve()
    if not source.is_dir() or source.is_symlink():
        print(f"Source directory not found or unsafe: {source}", file=sys.stderr)
        return 5

    # Preserve recursive inventory while refusing to follow symbolic-link files.
    files = sorted(
        (
            path
            for path in source.rglob("*")
            if path.is_file() and not path.is_symlink()
        ),
        key=lambda path: str(path.relative_to(source)).lower(),
    )
    ffprobe_available = shutil.which("ffprobe") is not None

    critical_errors: list[str] = []
    duplicate_findings: list[str] = []
    mismatch_findings: list[str] = []
    unsupported_findings: list[str] = []
    unavailable_findings: list[str] = []
    inventory: list[tuple[Path, dict[str, Any] | None, str]] = []

    if not files:
        critical_errors.append("No files were found in the intake source.")

    # Preserve case-insensitive duplicate-basename detection exactly.
    if args.no_duplicate_check:
        unavailable_findings.append("Duplicate-basename detection was skipped.")
    else:
        by_name: dict[str, list[Path]] = {}
        for path in files:
            by_name.setdefault(path.name.lower(), []).append(path)
        for duplicate_paths in by_name.values():
            if len(duplicate_paths) > 1:
                display = ", ".join(
                    f"`{path.relative_to(source)}`" for path in duplicate_paths
                )
                duplicate_findings.append(display)

    # Inspect each file independently so one unreadable candidate does not hide
    # the rest of the delivery inventory.
    for path in files:
        relative = path.relative_to(source)
        extension = path.suffix.lower()
        metadata: dict[str, Any] | None = None
        inspection = "not-inspected"

        if extension in AUDIO_EXTENSIONS:
            if ffprobe_available:
                metadata, error = ffprobe_metadata(path)
                if error:
                    critical_errors.append(f"Unreadable audio file `{relative}`: {error}")
                    inspection = "unreadable"
                else:
                    inspection = "inspected"
                    if metadata:
                        actual_rate = metadata.get("sample_rate")
                        actual_depth = metadata.get("bit_depth")
                        if (
                            args.expected_sample_rate
                            and actual_rate
                            and actual_rate != args.expected_sample_rate
                        ):
                            mismatch_findings.append(
                                f"`{relative}`: {actual_rate} Hz; "
                                f"expected {args.expected_sample_rate} Hz."
                            )
                        if (
                            args.expected_bit_depth
                            and actual_depth
                            and actual_depth != args.expected_bit_depth
                        ):
                            mismatch_findings.append(
                                f"`{relative}`: {actual_depth}-bit; "
                                f"expected {args.expected_bit_depth}-bit."
                            )
        else:
            unsupported_findings.append(f"`{relative}`")

        inventory.append((path, metadata, inspection))

    if not ffprobe_available:
        unavailable_findings.append(
            "ffprobe is not installed; enhanced audio inspection was unavailable."
        )

    # Warning counts retain v1.0.4 semantics. An explicitly skipped duplicate
    # check is documented but does not itself become a warning.
    warning_count = (
        len(duplicate_findings)
        + len(mismatch_findings)
        + len(unsupported_findings)
        + (0 if ffprobe_available else 1)
    )

    enhanced = "available through ffprobe" if ffprobe_available else "unavailable"
    lines: list[str] = [
        "## Intake Summary",
        "",
        f"- Source: `{source}`",
        f"- Files discovered: {len(files)}",
        f"- Blocking errors: {len(critical_errors)}",
        f"- Warnings: {warning_count}",
        f"- Expected sample rate: {args.expected_sample_rate or 'not specified'}",
        f"- Expected bit depth: {args.expected_bit_depth or 'not specified'}",
        f"- Enhanced inspection: {enhanced}",
        "",
        "## Critical Errors",
        "",
    ]
    lines.extend(markdown_items(critical_errors))

    lines.extend(["", "## Duplicate Filenames", ""])
    lines.extend(markdown_items(duplicate_findings))

    lines.extend(["", "## Project-Format Mismatches", ""])
    lines.extend(markdown_items(mismatch_findings))

    lines.extend(["", "## Unsupported or Non-Audio Files", ""])
    lines.extend(markdown_items(unsupported_findings))

    lines.extend(["", "## Skipped or Unavailable Checks", ""])
    lines.extend(markdown_items(unavailable_findings))

    lines.extend(
        [
            "",
            "## Source Inventory",
            "",
            "| File | Size (bytes) | Technical details |",
            "|---|---:|---|",
        ]
    )
    for path, metadata, inspection in inventory:
        relative = str(path.relative_to(source)).replace("|", "\\|")
        lines.append(
            f"| `{relative}` | {path.stat().st_size} | "
            f"{format_technical(metadata, inspection)} |"
        )
    if not inventory:
        lines.append("| _No files_ | 0 | — |")

    recommendations: list[str] = []
    if critical_errors:
        recommendations.append(
            "Resolve blocking errors before preparing `Working_Audio/`."
        )
    if mismatch_findings:
        recommendations.append(
            "Review project-format mismatches before conversion or DAW import."
        )
    if duplicate_findings:
        recommendations.append(
            "Review duplicate filenames to avoid ambiguous DAW imports."
        )
    if unsupported_findings:
        recommendations.append(
            "Review unsupported or non-audio files and retain any required documentation."
        )
    if unavailable_findings:
        recommendations.append(
            "Document skipped or unavailable checks in `Preparation_Report.md`."
        )
    if not recommendations:
        recommendations.append("Intake is ready for manual audio preparation.")

    lines.extend(["", "## Preparation Recommendations", ""])
    lines.extend(f"- {item}" for item in recommendations)

    args.output.write_text(
        "\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n"
    )
    write_summary(
        args.summary_output,
        file_count=len(files),
        error_count=len(critical_errors),
        warning_count=warning_count,
        ffprobe_available=ffprobe_available,
    )
    return 5 if critical_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
