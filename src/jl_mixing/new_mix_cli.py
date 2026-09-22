"""Human-facing new-mix command backed by the cross-platform project service."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from .context import resolve_client_reference
from .errors import ArgumentError, JLMixingError, ValidationError
from .project import ProjectCreateRequest, create_project

_USAGE = """Usage:
  new-mix PROJECT_NAME [options]
  new-mix --project PROJECT_NAME [options]

Options:
  --client ID_OR_PATH      Client ID or client-directory path
  --project NAME           Project display name; alternative to PROJECT_NAME
  --project-id ID          Stable project slug (default: derived from name)
  --artist NAME            Artist or program name (default: client artist, then client name)
  --album TITLE            Album or collection title
  --producer NAME          Producer name
  --engineer NAME          Mix engineer
  --bpm NUMBER             Tempo
  --key TEXT               Musical key
  --time-signature TEXT    Time signature
  --sample-rate HZ         Project sample rate
  --bit-depth BITS         Project bit depth
  --file-format FORMAT     WAV or AIFF
  --deadline YYYY-MM-DD    Project deadline
  --deliverables LIST      Comma-separated requested deliverables
  --description TEXT       Creative direction
  --source PATH            Initial client-delivery file or directory
  --cd                     Enter the project directory after creation
  --no-cd                  Remain in the current directory after creation
  --dry-run                Show the planned project without creating it
  -h, --help               Show this help
"""


def _removed_option(name: str) -> ArgumentError:
    messages = {
        "--project-type": (
            "--project-type was removed in JL Mixing 1.1.\n"
            "The v1.1 project manifest no longer stores a project type."
        ),
        "--daw": (
            "--daw was removed in JL Mixing 1.1.\n"
            "JL Mixing no longer manages DAW identity or configuration."
        ),
        "--template": (
            "--template was removed in JL Mixing 1.1.\n"
            "Manage native DAW projects and templates directly in 03_DAW_Project/."
        ),
        "--non-interactive": (
            "--non-interactive was removed in JL Mixing 1.1.\n"
            "new-mix already uses supplied values and inherited defaults without prompting."
        ),
    }
    return ArgumentError(messages[name])


def _parse_deliverables(value: str) -> list[str]:
    raw = value.split(",")
    if not raw or any(not item.strip() for item in raw):
        raise ValidationError(f"Invalid --deliverables list: {value}")
    values = [item.strip() for item in raw]
    if len(set(values)) != len(values):
        raise ValidationError("Requested deliverables must be unique.")
    return values


def _parse_bpm(value: str) -> float | int:
    try:
        parsed: float | int = int(value) if value.isdigit() else float(value)
    except ValueError as exc:
        raise ValidationError(f"BPM must be a positive number: {value}") from exc
    if parsed <= 0:
        raise ValidationError(f"BPM must be greater than zero: {value}")
    return parsed


def _parse(args: list[str]) -> tuple[ProjectCreateRequest | None, bool]:
    if args == ["-h"] or args == ["--help"]:
        return None, True

    project_name: str | None = None
    positional_seen = False
    project_option_seen = False
    client_reference: str | None = None
    values: dict[str, object] = {
        "project_id": None,
        "artist": None,
        "album": "",
        "producer": "",
        "engineer": None,
        "bpm": None,
        "musical_key": "",
        "time_signature": "",
        "sample_rate": None,
        "bit_depth": None,
        "file_format": None,
        "deadline": None,
        "deliverables": None,
        "description": "",
        "source": None,
    }
    cd_value: bool | None = None
    cd_seen = False
    no_cd_seen = False
    dry_run = False
    option_map = {
        "--client": "client",
        "--project-id": "project_id",
        "--artist": "artist",
        "--album": "album",
        "--producer": "producer",
        "--engineer": "engineer",
        "--bpm": "bpm",
        "--key": "musical_key",
        "--time-signature": "time_signature",
        "--sample-rate": "sample_rate",
        "--bit-depth": "bit_depth",
        "--file-format": "file_format",
        "--deadline": "deadline",
        "--deliverables": "deliverables",
        "--description": "description",
        "--source": "source",
    }

    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"--project-type", "--daw", "--template", "--non-interactive"}:
            raise _removed_option(arg)
        if arg in {"-h", "--help"}:
            return None, True
        if arg == "--project":
            if positional_seen:
                raise ArgumentError("Project name cannot be specified both positionally and with --project.")
            index += 1
            if index >= len(args):
                raise ArgumentError("--project requires a value.")
            if project_option_seen:
                raise ArgumentError("Project name cannot be specified more than once.")
            project_name = args[index]
            project_option_seen = True
        elif arg == "--cd":
            cd_seen = True
            cd_value = True
        elif arg == "--no-cd":
            no_cd_seen = True
            cd_value = False
        elif arg == "--dry-run":
            dry_run = True
        elif arg in option_map:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            field = option_map[arg]
            if field == "client":
                client_reference = value
            elif arg == "--sample-rate":
                try:
                    values[field] = int(value)
                except ValueError as exc:
                    raise ValidationError(f"Unsupported sample rate: {value}") from exc
            elif arg == "--bit-depth":
                try:
                    values[field] = int(value)
                except ValueError as exc:
                    raise ValidationError(f"Unsupported bit depth: {value}") from exc
            elif arg == "--bpm":
                values[field] = _parse_bpm(value)
            elif arg == "--deliverables":
                values[field] = _parse_deliverables(value)
            elif arg == "--source":
                values[field] = Path(value)
            else:
                values[field] = value
        elif arg.startswith("-"):
            raise ArgumentError(f"Unknown option: {arg}")
        else:
            if project_option_seen:
                raise ArgumentError("Project name cannot be specified both positionally and with --project.")
            if positional_seen:
                raise ArgumentError(f"Unexpected positional argument: {arg}")
            project_name = arg
            positional_seen = True
        index += 1

    if cd_seen and no_cd_seen:
        raise ArgumentError("--cd and --no-cd cannot be used together.")
    if dry_run and (cd_seen or no_cd_seen):
        raise ArgumentError("--cd and --no-cd cannot be used with --dry-run.")
    if project_name is None:
        raise ArgumentError("A project name is required. Supply it positionally or with --project.")

    configured_root = os.environ.get("JL_MIXING_ROOT")
    context = Path(configured_root) if configured_root else Path.cwd()
    client_root = resolve_client_reference(client_reference, context)
    return ProjectCreateRequest(
        client_root=client_root,
        project_name=project_name,
        project_id=values["project_id"] if isinstance(values["project_id"], str) else None,
        artist=values["artist"] if isinstance(values["artist"], str) else None,
        album=str(values["album"]),
        producer=str(values["producer"]),
        engineer=values["engineer"] if isinstance(values["engineer"], str) else None,
        bpm=values["bpm"] if isinstance(values["bpm"], (int, float)) else None,
        musical_key=str(values["musical_key"]),
        time_signature=str(values["time_signature"]),
        sample_rate=values["sample_rate"] if isinstance(values["sample_rate"], int) else None,
        bit_depth=values["bit_depth"] if isinstance(values["bit_depth"], int) else None,
        file_format=values["file_format"] if isinstance(values["file_format"], str) else None,
        deadline=values["deadline"] if isinstance(values["deadline"], str) else None,
        deliverables=values["deliverables"] if isinstance(values["deliverables"], list) else None,
        description=str(values["description"]),
        source=values["source"] if isinstance(values["source"], Path) else None,
        change_directory=cd_value,
        dry_run=dry_run,
    ), False


def _shell_quote(path: Path) -> str:
    return shlex.quote(str(path))


def _print_summary(result, heading: str) -> None:
    manifest = result.manifest
    audio = manifest["audio"]
    delivery = manifest["delivery"]
    source_display = str(result.source_plan.source) if result.source_plan is not None else "<none>"
    print(heading)
    print()
    print(f"Client:                     {result.client_snapshot['source_client']['client_name']} ({manifest['client']['client_id']})")
    print(f"Project:                    {manifest['project_name']}")
    print(f"Project ID:                 {manifest['project_id']}")
    print(f"Project folder:             {result.project_root}")
    print(f"Artist:                     {manifest['artist']}")
    print(f"Engineer:                   {manifest['mix_engineer'] or '<not set>'}")
    print(f"Audio format:               {audio['sample_rate']} Hz / {audio['bit_depth']}-bit / {audio['file_format']}")
    print(f"Delivery method:            {delivery['method']}")
    print(f"Requested deliverables:     {', '.join(delivery['requested_deliverables'])}")
    print(f"Source:                     {source_display}")
    print("Initial state:              In progress")
    print("Current revision:           1")
    print(f"Initial revision:           {result.initial_revision_root}")
    print(f"Automatic directory change: {'enabled' if result.effective_cd else 'disabled'}")


def _write_cd_result(path: Path) -> bool:
    result_file = os.environ.get("JL_MIXING_CD_RESULT_FILE")
    if not result_file:
        return False
    target = Path(result_file)
    if not target.is_absolute() or target.is_symlink() or not target.is_file():
        raise ValidationError(f"Shell-integration result file is missing or unsafe: {target}")
    target.write_text(str(path) + "\n", encoding="utf-8", newline="\n")
    return True


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        request, help_only = _parse(args)
        if help_only:
            print(_USAGE, end="")
            return 0
        assert request is not None
        result = create_project(request)
        if request.dry_run:
            _print_summary(result, "Dry run — no changes made.")
            print("\nWould create:")
            for relative in (
                "00_Admin/",
                "01_Client_Files/Original_Delivery/",
                "01_Client_Files/References/",
                "01_Client_Files/Documentation/",
                "02_Audio_Preparation/Working_Audio/",
                "02_Audio_Preparation/Rejected_Files/",
                "03_DAW_Project/",
                "04_Revisions/",
                "04_Revisions/Revision_01/",
                "04_Revisions/Revision_01/Revision_Notes.md",
                "05_Final_Delivery/Stems/",
                "06_Recall/External_Files/",
                "06_Recall/Screenshots/",
            ):
                print(f"  {relative}")
            if result.source_plan is not None:
                print("\nWould copy into 01_Client_Files/Original_Delivery/:")
                if not result.source_plan.entries:
                    print("  <source directory is empty>")
                else:
                    for entry in result.source_plan.entries:
                        suffix = "/" if entry.type == "directory" else ""
                        print(f"  {entry.path}{suffix}")
            print("\nAfter creation:")
            print(f"  cd {_shell_quote(result.project_root)}")
            print("  approve-mix")
            return 0

        result_written = False
        if result.effective_cd:
            result_written = _write_cd_result(result.project_root)

        _print_summary(result, "Project created successfully.")
        print(f"Manifest:                    {result.project_root / '00_Admin' / 'project-manifest.json'}")
        print(f"Client snapshot:             {result.project_root / '00_Admin' / 'client-profile-snapshot.json'}")
        if result.effective_cd and not result_written:
            print(
                "\nAutomatic directory change could not be performed because JL Mixing shell\n"
                "integration is not active."
            )
        print("\nNext:")
        if not result.effective_cd or not result_written:
            print(f"  cd {_shell_quote(result.project_root)}")
        print("  approve-mix")
        return 0
    except JLMixingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
