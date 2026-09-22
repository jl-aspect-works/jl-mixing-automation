"""v1.4-compatible human validate-intake command on the Python runtime."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .context import resolve_project
from .errors import ArgumentError, JLMixingError, ValidationError
from .intake_incremental import validate_intake_incremental
from .markdown import replace_managed_section
from .validation import require_bit_depth, require_sample_rate

_BEGIN = "<!-- BEGIN AUTOMATED SECTION -->"
_END = "<!-- END AUTOMATED SECTION -->"
_CACHE_NAME = "intake-validation-cache.json"

_USAGE = """Usage: validate-intake [options]

Options:
  --project PATH             Explicit project path
  --source PATH              Intake source directory
  --expected-sample-rate HZ  Override expected sample rate
  --expected-bit-depth BITS  Override expected bit depth
  --no-duplicate-check       Skip exact duplicate-content checking
  --dry-run                  Build and print a temporary report without updating cache
  -h, --help                 Show this help
"""


def _read_manifest(project: Path) -> dict[str, object]:
    path = project / "00_Admin" / "project-manifest.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Project manifest is unreadable: {path}") from exc
    if not isinstance(document, dict):
        raise ValidationError(f"Project manifest is invalid: {path}")
    return document


def _parse(args: list[str]) -> tuple[Path | None, Path | None, int | None, int | None, bool, bool]:
    project: Path | None = None
    source: Path | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    duplicate_check = True
    dry_run = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"-h", "--help"}:
            print(_USAGE, end="")
            raise SystemExit(0)
        if arg == "--report-only":
            raise ArgumentError(
                "--report-only was removed in JL Mixing 1.1.\n"
                "validate-intake is always report-only and never modifies intake source files."
            )
        if arg == "--non-interactive":
            raise ArgumentError(
                "--non-interactive was removed in JL Mixing 1.1.\n"
                "validate-intake does not prompt for input."
            )
        if arg in {"--project", "--source", "--expected-sample-rate", "--expected-bit-depth"}:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--project":
                project = Path(value)
            elif arg == "--source":
                source = Path(value)
            elif arg == "--expected-sample-rate":
                try:
                    sample_rate = int(value)
                except ValueError as exc:
                    raise ValidationError(f"Unsupported expected sample rate: {value}") from exc
            else:
                try:
                    bit_depth = int(value)
                except ValueError as exc:
                    raise ValidationError(f"Unsupported expected bit depth: {value}") from exc
        elif arg == "--no-duplicate-check":
            duplicate_check = False
        elif arg == "--dry-run":
            dry_run = True
        else:
            raise ArgumentError(f"Unknown option: {arg}")
        index += 1
    return project, source, sample_rate, bit_depth, duplicate_check, dry_run


def command(args: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if args is None else args)
    try:
        project_ref, source_ref, sample_rate_override, bit_depth_override, duplicate_check, dry_run = _parse(argv)
        project = resolve_project(project_ref, Path.cwd())
        manifest = _read_manifest(project)
        project_name = manifest.get("project_name")
        if not isinstance(project_name, str) or not project_name:
            raise ValidationError("Project manifest does not contain a valid project_name.")
        audio = manifest.get("audio") if isinstance(manifest.get("audio"), dict) else {}
        sample_rate = require_sample_rate(
            sample_rate_override if sample_rate_override is not None else audio.get("sample_rate")
        )
        bit_depth = require_bit_depth(
            bit_depth_override if bit_depth_override is not None else audio.get("bit_depth")
        )
        expected_format = audio.get("file_format") if isinstance(audio.get("file_format"), str) else None
        source = (source_ref or (project / "01_Client_Files" / "Original_Delivery")).expanduser()
        if not source.is_absolute():
            source = Path.cwd() / source
        source = source.resolve()
        if source.is_symlink() or not source.is_dir():
            raise ValidationError(f"Intake source directory not found or unsafe: {source}")

        report = project / "00_Admin" / "Intake_Report.md"
        if report.is_symlink() or not report.is_file():
            raise ValidationError(f"Intake report not found or unsafe: {report}")
        cache_path = project / "00_Admin" / _CACHE_NAME

        result = validate_intake_incremental(
            source,
            expected_sample_rate=sample_rate,
            expected_bit_depth=bit_depth,
            expected_format=expected_format,
            duplicate_check=duplicate_check,
            cache_path=cache_path,
            update_cache=not dry_run,
        )
        exit_code = 5 if result.blocked else 0
        if dry_run:
            print(result.report_markdown, end="")
            return exit_code

        replace_managed_section(report, _BEGIN, _END, result.report_markdown)
        if result.blocked:
            print("Intake validation completed with blocking errors.\n")
        else:
            print("Intake validation completed.\n")
        print(f"Project:         {project_name}")
        print(f"Source:          {source}")
        print(f"Files inspected: {result.files_discovered}")
        print(f"Cache reused:    {result.cache_reused}")
        print(f"Files validated: {result.files_validated}")
        print(f"Blocking errors: {result.blocking_errors}")
        print(f"Warnings:        {result.warnings}")
        print(f"Report:          {report}")
        print("\nNext:")
        if result.blocked:
            print("  Review and resolve the critical errors in 00_Admin/Intake_Report.md")
        else:
            print("  Review 00_Admin/Intake_Report.md")
            print("  Prepare accepted audio in 02_Audio_Preparation/Working_Audio/")
        return exit_code
    except JLMixingError as exc:
        for line in str(exc).splitlines() or [str(exc)]:
            print(f"Error: {line}", file=sys.stderr)
        return exc.exit_code


def main() -> None:
    raise SystemExit(command())


if __name__ == "__main__":
    main()
