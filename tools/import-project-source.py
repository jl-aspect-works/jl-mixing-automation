#!/usr/bin/env python3
"""Safely plan and copy a new project's initial client delivery.

The helper deliberately uses ``lstat``/``scandir`` so symbolic links are never
followed. ``scan`` records the exact relative directory/file structure before
project staging begins. ``copy`` rescans and compares that structure before
copying, preventing a changed source tree from silently altering the import.
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


def validate_component(name: str, path: Path) -> None:
    """Reject control characters that make CLI/report output ambiguous."""

    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        fail(f"Control characters are not allowed in source names: {path}")


def classify(path: Path) -> str:
    """Return file/directory without following a symbolic link."""

    try:
        mode = path.lstat().st_mode
    except OSError as error:
        fail(f"Unable to inspect source path {path}: {error}")
    if stat.S_ISLNK(mode):
        fail(f"Symbolic links are not allowed in source imports: {path}")
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    fail(f"Unsupported source filesystem object: {path}")
    raise AssertionError("unreachable")


def build_plan(source: Path) -> dict[str, Any]:
    """Return a deterministic, case-insensitive-collision-safe source plan."""

    source_type = classify(source)
    entries: list[dict[str, str]] = []
    seen: dict[str, str] = {}

    def add_entry(relative: Path, entry_type: str) -> None:
        display = relative.as_posix()
        key = display.casefold()
        if key in seen:
            fail(
                "Case-insensitive source-path collision: "
                f"{seen[key]!r} and {display!r}"
            )
        seen[key] = display
        entries.append({"type": entry_type, "path": display})

    if source_type == "file":
        validate_component(source.name, source)
        add_entry(Path(source.name), "file")
    else:

        def walk(directory: Path, relative_directory: Path) -> None:
            try:
                children = sorted(
                    os.scandir(directory),
                    key=lambda item: (item.name.casefold(), item.name),
                )
            except OSError as error:
                fail(f"Unable to read source directory {directory}: {error}")
            for child in children:
                child_path = Path(child.path)
                validate_component(child.name, child_path)
                relative = relative_directory / child.name
                entry_type = classify(child_path)
                add_entry(relative, entry_type)
                if entry_type == "directory":
                    walk(child_path, relative)

        walk(source, Path())

    entries.sort(key=lambda item: (item["path"].casefold(), item["path"], item["type"]))
    return {
        "source_type": source_type,
        "source": str(source),
        "entries": entries,
    }


def write_plan(source: Path, plan_path: Path) -> None:
    plan = build_plan(source)
    plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def copy_from_plan(source: Path, destination: Path, plan_path: Path) -> None:
    expected = json.loads(plan_path.read_text(encoding="utf-8"))
    current = build_plan(source)
    if (
        current.get("source_type") != expected.get("source_type")
        or current.get("entries") != expected.get("entries")
    ):
        fail("Source import changed after preflight; no project was created.")

    if destination.is_symlink() or not destination.is_dir():
        fail(f"Source-import destination is missing or unsafe: {destination}")
    if any(destination.iterdir()):
        fail(f"Source-import destination must be empty: {destination}")

    source_type = current["source_type"]
    entries = current["entries"]
    directories = [item for item in entries if item["type"] == "directory"]
    files = [item for item in entries if item["type"] == "file"]

    # Create directories shallowest-first, then copy files without following
    # links. Directory timestamps/modes are restored deepest-first afterward.
    for item in sorted(
        directories,
        key=lambda value: (value["path"].count("/"), value["path"]),
    ):
        (destination / item["path"]).mkdir(parents=True, exist_ok=False)

    for item in files:
        relative = Path(item["path"])
        source_file = source if source_type == "file" else source / relative
        destination_file = destination / relative
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file, follow_symlinks=False)

    for item in sorted(
        directories,
        key=lambda value: value["path"].count("/"),
        reverse=True,
    ):
        relative = Path(item["path"])
        shutil.copystat(
            source / relative,
            destination / relative,
            follow_symlinks=False,
        )


def main(args: Namespace) -> int:
    if args.command == "scan":
        write_plan(args.source, args.plan)
    else:
        copy_from_plan(args.source, args.destination, args.plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(parser().parse_args()))
