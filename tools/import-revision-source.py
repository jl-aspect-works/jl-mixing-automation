#!/usr/bin/env python3
"""Safely plan and copy immediate files into a new revision directory.

The helper never follows symbolic links. A directory source may contain only
immediate regular files; nested directories and special filesystem objects are
rejected. The exact planned filenames are rescanned before copying so a changed
source cannot silently alter the committed revision.
"""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
import json
import os
from pathlib import Path
import shutil
import stat
import sys
from typing import Any

VALIDATION_ERROR = 5
RESERVED_NAME = "revision_notes.md"


def parser() -> ArgumentParser:
    result = ArgumentParser(description=__doc__)
    subcommands = result.add_subparsers(dest="command", required=True)

    scan = subcommands.add_parser("scan", help="validate a source and write a plan")
    scan.add_argument("source", type=Path)
    scan.add_argument("plan", type=Path)

    copy = subcommands.add_parser("copy", help="copy a previously scanned source")
    copy.add_argument("source", type=Path)
    copy.add_argument("destination", type=Path)
    copy.add_argument("plan", type=Path)
    return result


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(VALIDATION_ERROR)


def classify(path: Path) -> str:
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        fail(f"Unable to inspect revision source {path}: {error}")
    if stat.S_ISLNK(mode):
        fail(f"Symbolic links are not allowed in revision sources: {path}")
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    fail(f"Unsupported revision source filesystem object: {path}")
    raise AssertionError("unreachable")


def validate_name(name: str, path: Path) -> None:
    if not name or name in {".", ".."}:
        fail(f"Unsafe revision source name: {path}")
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        fail(f"Control characters are not allowed in revision source names: {path}")
    if name.casefold() == RESERVED_NAME:
        fail(f"Revision source may not replace Revision_Notes.md: {path}")


def build_plan(source: Path) -> dict[str, Any]:
    source_type = classify(source)
    names: list[str] = []
    seen: dict[str, str] = {RESERVED_NAME: "Revision_Notes.md"}

    def add_file(path: Path) -> None:
        validate_name(path.name, path)
        key = path.name.casefold()
        if key in seen:
            fail(
                "Case-insensitive revision destination collision: "
                f"{seen[key]!r} and {path.name!r}"
            )
        seen[key] = path.name
        names.append(path.name)

    if source_type == "file":
        add_file(source)
    else:
        try:
            children = sorted(
                os.scandir(source), key=lambda item: (item.name.casefold(), item.name)
            )
        except OSError as error:
            fail(f"Unable to read revision source directory {source}: {error}")
        for child in children:
            child_path = Path(child.path)
            entry_type = classify(child_path)
            if entry_type == "directory":
                fail(f"Nested directories are not allowed in revision sources: {child_path}")
            add_file(child_path)

    names.sort(key=lambda value: (value.casefold(), value))
    return {"source_type": source_type, "source": str(source), "files": names}


def write_plan(source: Path, plan_path: Path) -> None:
    plan_path.write_text(
        json.dumps(build_plan(source), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def copy_from_plan(source: Path, destination: Path, plan_path: Path) -> None:
    try:
        expected = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"Unable to read revision source plan {plan_path}: {error}")
    current = build_plan(source)
    if current.get("source_type") != expected.get("source_type") or current.get(
        "files"
    ) != expected.get("files"):
        fail("Revision source changed after preflight; no revision was created.")

    if destination.is_symlink() or not destination.is_dir():
        fail(f"Revision destination is missing or unsafe: {destination}")
    if any(destination.iterdir()):
        fail(f"Revision destination must be empty before source copying: {destination}")

    for name in current["files"]:
        source_file = source if current["source_type"] == "file" else source / name
        destination_file = destination / name
        shutil.copy2(source_file, destination_file, follow_symlinks=False)


def main(args: Namespace) -> int:
    if args.command == "scan":
        write_plan(args.source, args.plan)
    else:
        copy_from_plan(args.source, args.destination, args.plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(parser().parse_args()))
