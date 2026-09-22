"""Human-facing new-revision command backed by the cross-platform revision service."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from .context import resolve_project
from .errors import ArgumentError, JLMixingError
from .revision import RevisionCreateRequest, RevisionCreateResult, create_revision

_USAGE = """Usage: new-revision [options]\n\nOptions:\n  --project PATH       Explicit project directory\n  --description TEXT   Revision description\n  --source PATH        Mix-print file or directory of immediate files to copy\n  --cd                 Enter the new revision directory after creation\n  --no-cd              Remain in the current directory after creation\n  --dry-run            Show the planned revision without creating it\n  -h, --help           Show this help\n"""


def _parse(args: list[str]) -> tuple[RevisionCreateRequest | None, bool]:
    if args in (["-h"], ["--help"]):
        return None, True
    project: Path | None = None
    description: str | None = None
    source: Path | None = None
    cd_value: bool | None = None
    cd_seen = False
    no_cd_seen = False
    dry_run = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--non-interactive":
            raise ArgumentError(
                "--non-interactive was removed in JL Mixing 1.1.\n"
                "new-revision already uses supplied values and defaults without prompting."
            )
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
        elif arg in {"--project", "--description", "--source"}:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--project":
                project = Path(value)
            elif arg == "--description":
                description = value
            else:
                source = Path(value)
        else:
            raise ArgumentError(f"Unknown option: {arg}")
        index += 1

    if cd_seen and no_cd_seen:
        raise ArgumentError("--cd and --no-cd are mutually exclusive.")
    if dry_run and (cd_seen or no_cd_seen):
        raise ArgumentError("--cd and --no-cd cannot be combined with --dry-run.")

    project_root = resolve_project(project, Path.cwd())
    return RevisionCreateRequest(
        project_root=project_root,
        description=description,
        source=source,
        change_directory=cd_value,
        dry_run=dry_run,
    ), False


def _shell_quote(path: Path) -> str:
    return shlex.quote(str(path))


def _write_cd_result(path: Path) -> bool:
    result_file = os.environ.get("JL_MIXING_CD_RESULT_FILE")
    if not result_file:
        return False
    target = Path(result_file)
    if not target.is_absolute() or target.is_symlink() or not target.is_file():
        raise ArgumentError(f"Shell-integration result file is missing or unsafe: {target}")
    target.write_text(str(path) + "\n", encoding="utf-8", newline="\n")
    return True


def _pointer(value: object) -> str:
    return "null" if value is None else str(value)


def _transition() -> str:
    return "->" if os.name == "nt" else "→"


def _print_summary(result: RevisionCreateResult, heading: str, *, planned: bool) -> None:
    print(heading)
    print()
    print(f"Project:                    {result.manifest['project_name']}")
    if planned:
        print(f"Current revision:           {result.previous_revision}")
        print(f"New revision:               {result.number}")
    else:
        print(f"Revision:                   {result.number}")
    print(f"Description:                {result.description}")
    print(f"Revision folder:            {result.revision_root}")
    source_display = str(result.source_plan.source) if result.source_plan is not None else "<none>"
    print(f"Source:                     {source_display}")
    print(f"Automatic directory change: {'enabled' if result.effective_cd else 'disabled'}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        request, help_only = _parse(args)
        if help_only:
            print(_USAGE, end="")
            return 0
        assert request is not None
        result = create_revision(request)
        if request.dry_run:
            _print_summary(result, "Dry run — no changes made.", planned=True)
            revision_name = result.revision_root.name
            print("\nWould create:")
            print(f"  {revision_name}/")
            print(f"  {revision_name}/Revision_Notes.md")
            if result.source_plan is not None:
                if not result.source_plan.files:
                    print("  <source directory contains no files>")
                else:
                    for name in result.source_plan.files:
                        print(f"  {revision_name}/{name}")
            print("\nWould update:")
            print(f"  state.current_revision: {result.previous_revision} {_transition()} {result.number}")
            print(f"  revisions: append Revision {result.number}")
            print("  metadata.last_modified_at")
            print("\nWould preserve:")
            print(f"  state.approved_revision: {_pointer(result.manifest['state']['approved_revision'])}")
            print(f"  state.delivered_revision: {_pointer(result.manifest['state']['delivered_revision'])}")
            print("\nAfter creation:")
            print(f"  cd {_shell_quote(result.revision_root)}")
            print("  approve-mix")
            return 0

        result_written = False
        if result.effective_cd:
            result_written = _write_cd_result(result.revision_root)

        _print_summary(result, "Revision created successfully.", planned=False)
        print("Project state:              In progress")
        if result.effective_cd and not result_written:
            print(
                "\nAutomatic directory change could not be performed because JL Mixing shell\n"
                "integration is not active."
            )
        print("\nNext:")
        if not result.effective_cd or not result_written:
            print(f"  cd {_shell_quote(result.revision_root)}")
        print("  approve-mix")
        return 0
    except JLMixingError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
