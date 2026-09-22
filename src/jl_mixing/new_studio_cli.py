"""Human-facing new-studio command backed by the cross-platform studio service."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .errors import ArgumentError, JLMixingError, ValidationError
from .studio import StudioCreateRequest, create_studio

_USAGE = """Usage: new-studio [options]\n\nOptions:\n  --root PATH          Workspace root (default: ~/Music/Mixes)\n  --name NAME          Studio name (default: Mixing Studio)\n  --engineer NAME      Default mix engineer\n  --sample-rate HZ     Default sample rate (default: 48000)\n  --bit-depth BITS     Default bit depth (default: 24)\n  --file-format FORMAT WAV or AIFF (default: WAV)\n  --default-cd         Enable automatic directory changes by default\n  --no-default-cd      Disable automatic directory changes by default\n  --dry-run            Show the planned workspace without creating it\n  -h, --help           Show this help\n"""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse(args: list[str]) -> tuple[StudioCreateRequest | None, bool]:
    if args in (["-h"], ["--help"]):
        return None, True
    default_root = os.environ.get("JL_MIXING_ROOT") or str(Path.home() / "Music" / "Mixes")
    root = Path(default_root)
    name = "Mixing Studio"
    engineer = ""
    sample_rate = 48000
    bit_depth = 24
    file_format = "WAV"
    default_cd = False
    default_cd_seen = False
    no_default_cd_seen = False
    dry_run = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"-h", "--help"}:
            return None, True
        if arg == "--daw":
            raise ArgumentError("--daw was removed in JL Mixing 1.1.\nDAW projects and templates are no longer managed by JL Mixing.")
        if arg == "--non-interactive":
            raise ArgumentError("--non-interactive was removed in JL Mixing 1.1.\nnew-studio already uses supplied values and defaults without prompting.")
        if arg in {"--root", "--name", "--engineer", "--sample-rate", "--bit-depth", "--file-format"}:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--root":
                root = Path(value)
            elif arg == "--name":
                name = value
            elif arg == "--engineer":
                engineer = value
            elif arg == "--sample-rate":
                try:
                    sample_rate = int(value)
                except ValueError as exc:
                    raise ValidationError(f"Unsupported sample rate: {value}") from exc
            elif arg == "--bit-depth":
                try:
                    bit_depth = int(value)
                except ValueError as exc:
                    raise ValidationError(f"Unsupported bit depth: {value}") from exc
            else:
                file_format = value
        elif arg == "--default-cd":
            default_cd_seen = True
            default_cd = True
        elif arg == "--no-default-cd":
            no_default_cd_seen = True
            default_cd = False
        elif arg == "--dry-run":
            dry_run = True
        elif arg.startswith("-"):
            raise ArgumentError(f"Unknown option: {arg}")
        else:
            raise ArgumentError(f"Unexpected positional argument: {arg}")
        index += 1

    if default_cd_seen and no_default_cd_seen:
        raise ArgumentError("--default-cd and --no-default-cd cannot be used together.")
    if not str(root).strip():
        raise ValidationError("studio root must not be empty.")
    return StudioCreateRequest(
        root=root,
        name=name,
        engineer=engineer,
        sample_rate=sample_rate,
        bit_depth=bit_depth,
        file_format=file_format,
        default_cd=default_cd,
        dry_run=dry_run,
    ), False


def _print_summary(result, heading: str) -> None:
    document = result.document
    defaults = document["defaults"]
    audio = defaults["audio"]
    engineer = defaults["mix_engineer"] or "<not set>"
    default_cd = document["cli"]["change_directory_after_create"] is True
    print(heading)
    print()
    print(f"Root:                       {result.root}")
    print(f"Studio:                     {document['studio_name']}")
    print(f"Engineer:                   {engineer}")
    print(f"Audio format:               {audio['sample_rate']} Hz / {audio['bit_depth']}-bit / {audio['file_format']}")
    print(f"Automatic directory change: {'enabled' if default_cd else 'disabled'}")
    if default_cd:
        shell = "active" if _truthy(os.environ.get("JL_MIXING_SHELL_INTEGRATION")) else "not detected"
        print(f"Shell integration:           {shell}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        request, help_only = _parse(args)
        if help_only:
            print(_USAGE, end="")
            return 0
        assert request is not None
        result = create_studio(request)
        default_cd = result.document["cli"]["change_directory_after_create"] is True
        shell_active = _truthy(os.environ.get("JL_MIXING_SHELL_INTEGRATION"))
        if request.dry_run:
            dry_run_heading = "Dry run - no changes made." if os.name == "nt" else "Dry run — no changes made."
            _print_summary(result, dry_run_heading)
            print("\nWould create:\n  Clients/\n  Studio/\n  Studio/studio.json")
            print("\nAfter creation:\n  new-client <client-id>")
            if default_cd and not shell_active:
                print("\nAutomatic directory changes require JL Mixing shell integration.")
                print("Until it is active, creation commands will print a copy-and-paste cd command.")
            return 0

        _print_summary(result, "Studio created successfully.")
        print(f"Configuration:                {result.studio_config}")
        if default_cd and not shell_active:
            print("\nAutomatic directory changes require JL Mixing shell integration.")
            print("Until it is active, creation commands will print a copy-and-paste cd command.")
        print("\nNext:\n  new-client <client-id>")
        return 0
    except JLMixingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
