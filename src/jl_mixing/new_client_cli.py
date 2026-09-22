"""Human-facing new-client command backed by the cross-platform client service."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from .client import ClientCreateRequest, create_client
from .context import studio_root
from .errors import ArgumentError, ContextError, JLMixingError, ValidationError

_USAGE = """Usage: new-client CLIENT_ID [options]\n\nOptions:\n  --name NAME             Display name (default: title-cased client ID)\n  --artist NAME           Default artist or program name\n  --sample-rate HZ        Default project sample rate\n  --bit-depth BITS        Default project bit depth\n  --file-format FORMAT    Default project format: WAV or AIFF\n  --delivery-method TEXT  Default delivery method\n  --deliverables LIST     Comma-separated requested deliverables\n  --root PATH             Studio root to target explicitly\n  --cd                    Enter the new client directory after creation\n  --no-cd                 Remain in the current directory after creation\n  --dry-run               Show the planned client without creating it\n  -h, --help              Show this help\n"""


def _removed_option(name: str) -> ArgumentError:
    if name == "--revision-limit":
        return ArgumentError(
            "--revision-limit was removed in JL Mixing 1.1.\n"
            "The v1.1 revision workflow has no included-revision limit."
        )
    return ArgumentError(
        "--non-interactive was removed in JL Mixing 1.1.\n"
        "new-client already uses supplied values and inherited defaults without prompting."
    )


def _parse_deliverables(value: str) -> list[str]:
    raw = value.split(",")
    if not raw or any(not item.strip() for item in raw):
        raise ValidationError(f"Invalid --deliverables list: {value}")
    values = [item.strip() for item in raw]
    if len(set(values)) != len(values):
        raise ValidationError("Requested deliverables must be unique.")
    return values


def _resolve_studio_root(explicit_root: str | None) -> Path:
    if explicit_root:
        return studio_root(Path(explicit_root).expanduser())

    configured_root = os.environ.get("JL_MIXING_ROOT")
    if configured_root:
        return studio_root(Path(configured_root).expanduser())

    try:
        return studio_root(Path.cwd())
    except ContextError:
        return studio_root(Path.home() / "Music" / "Mixes")


def _parse(args: list[str]) -> tuple[ClientCreateRequest | None, bool]:
    if not args:
        raise ArgumentError("client ID must not be empty.")
    if args == ["-h"] or args == ["--help"]:
        return None, True
    if args[0].startswith("-"):
        raise ArgumentError("client ID must not be empty.")

    client_id = args[0]
    values: dict[str, object] = {
        "client_name": None,
        "artist": "",
        "sample_rate": None,
        "bit_depth": None,
        "file_format": None,
        "delivery_method": None,
        "deliverables": None,
        "root": None,
    }
    cd_value: bool | None = None
    cd_seen = False
    no_cd_seen = False
    dry_run = False
    index = 1
    while index < len(args):
        arg = args[index]
        if arg in {"--revision-limit", "--non-interactive"}:
            raise _removed_option(arg)
        if arg in {"-h", "--help"}:
            return None, True
        if arg == "--cd":
            cd_seen = True
            cd_value = True
        elif arg == "--no-cd":
            no_cd_seen = True
            cd_value = False
        elif arg == "--dry-run":
            dry_run = True
        elif arg in {
            "--name",
            "--artist",
            "--sample-rate",
            "--bit-depth",
            "--file-format",
            "--delivery-method",
            "--deliverables",
            "--root",
        }:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--name":
                values["client_name"] = value
            elif arg == "--artist":
                values["artist"] = value
            elif arg == "--sample-rate":
                try:
                    values["sample_rate"] = int(value)
                except ValueError as exc:
                    raise ValidationError(f"Unsupported sample rate: {value}") from exc
            elif arg == "--bit-depth":
                try:
                    values["bit_depth"] = int(value)
                except ValueError as exc:
                    raise ValidationError(f"Unsupported bit depth: {value}") from exc
            elif arg == "--file-format":
                values["file_format"] = value
            elif arg == "--delivery-method":
                values["delivery_method"] = value
            elif arg == "--deliverables":
                values["deliverables"] = _parse_deliverables(value)
            else:
                values["root"] = value
        elif arg.startswith("-"):
            raise ArgumentError(f"Unknown option: {arg}")
        else:
            raise ArgumentError(f"Unexpected positional argument: {arg}")
        index += 1

    if cd_seen and no_cd_seen:
        raise ArgumentError("--cd and --no-cd cannot be used together.")
    if dry_run and (cd_seen or no_cd_seen):
        raise ArgumentError("--cd and --no-cd cannot be used with --dry-run.")

    root_value = values["root"] if isinstance(values["root"], str) else None
    root = _resolve_studio_root(root_value)
    return (
        ClientCreateRequest(
            studio_root=root,
            client_id=client_id,
            client_name=values["client_name"] if isinstance(values["client_name"], str) else None,
            artist=str(values["artist"]),
            sample_rate=values["sample_rate"] if isinstance(values["sample_rate"], int) else None,
            bit_depth=values["bit_depth"] if isinstance(values["bit_depth"], int) else None,
            file_format=values["file_format"] if isinstance(values["file_format"], str) else None,
            delivery_method=values["delivery_method"] if isinstance(values["delivery_method"], str) else None,
            deliverables=values["deliverables"] if isinstance(values["deliverables"], list) else None,
            change_directory=cd_value,
            dry_run=dry_run,
        ),
        False,
    )


def _shell_quote(path: Path) -> str:
    return shlex.quote(str(path))


def _print_summary(result, heading: str) -> None:
    doc = result.client_document
    defaults = doc["defaults"]
    audio = defaults["audio"]
    delivery = defaults["delivery"]
    artist = defaults.get("artist") or "<not set>"
    print(heading)
    print()
    print(f"Client ID:                  {doc['client_id']}")
    print(f"Client name:                {doc['client_name']}")
    print(f"Client folder:              {result.client_root}")
    print(f"Default artist:             {artist}")
    print(f"Audio format:               {audio['sample_rate']} Hz / {audio['bit_depth']}-bit / {audio['file_format']}")
    print(f"Delivery method:            {delivery['method']}")
    print(f"Requested deliverables:     {', '.join(delivery['requested_deliverables'])}")
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
        result = create_client(request)
        if request.dry_run:
            _print_summary(result, "Dry run — no changes made.")
            print("\nWould create:")
            print("  client.json")
            print("  Projects/")
            print("\nAfter creation:")
            print(f"  cd {_shell_quote(result.client_root)}")
            print('  new-mix --project "PROJECT NAME"')
            return 0

        result_written = False
        if result.effective_cd:
            result_written = _write_cd_result(result.client_root)

        _print_summary(result, "Client created successfully.")
        print(f"Configuration:               {result.client_root / 'client.json'}")
        if result.effective_cd and not result_written:
            print(
                "\nAutomatic directory change could not be performed because JL Mixing shell\n"
                "integration is not active."
            )
        print("\nNext:")
        if not result.effective_cd or not result_written:
            print(f"  cd {_shell_quote(result.client_root)}")
        print('  new-mix --project "PROJECT NAME"')
        return 0
    except JLMixingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
