"""Frozen macOS runtime bootstrap for JL Mixing Automation.

The public launchers invoke this bundled executable using the same internal
shape as CPython: ``python -m jl_mixing.<module> ...``. Only JL Mixing command
modules are accepted; this is an application runtime, not a general-purpose
Python interpreter.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from jl_mixing import (
    approve_mix_cli,
    cli,
    create_delivery_cli,
    macos_installer,
    new_client_cli,
    new_mix_cli,
    new_revision_cli,
    new_studio_cli,
    validate_intake_cli,
)

EntryPoint = Callable[[], int | None]

ENTRY_POINTS: dict[str, EntryPoint] = {
    "jl_mixing.cli": cli.main,
    "jl_mixing.new_studio_cli": new_studio_cli.main,
    "jl_mixing.new_client_cli": new_client_cli.main,
    "jl_mixing.new_mix_cli": new_mix_cli.main,
    "jl_mixing.validate_intake_cli": validate_intake_cli.main,
    "jl_mixing.new_revision_cli": new_revision_cli.main,
    "jl_mixing.approve_mix_cli": approve_mix_cli.main,
    "jl_mixing.create_delivery_cli": create_delivery_cli.main,
    "jl_mixing.macos_installer": macos_installer.main,
}


def _exit_code(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    print(value, file=sys.stderr)
    return 1


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] != "-m":
        print(
            "Error: JL Mixing bundled runtime requires '-m <jl_mixing module>'.",
            file=sys.stderr,
        )
        return 2

    module_name = sys.argv[2]
    entry_point = ENTRY_POINTS.get(module_name)
    if entry_point is None:
        print(f"Error: unsupported JL Mixing runtime module: {module_name}", file=sys.stderr)
        return 2

    sys.argv = [module_name, *sys.argv[3:]]
    try:
        result = entry_point()
    except SystemExit as exc:
        return _exit_code(exc.code)
    return _exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
