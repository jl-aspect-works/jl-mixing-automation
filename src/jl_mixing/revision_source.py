"""Cross-platform revision-source planning and copy primitives."""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from .errors import ContextError, UnsafeOperationError, ValidationError
from .os_metadata import is_ignored_os_metadata_path

_RESERVED_NAME = "revision_notes.md"


@dataclass(frozen=True)
class RevisionSourcePlan:
    source_type: str
    source: Path
    files: tuple[str, ...]


def _classify(path: Path) -> str:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise ContextError(f"Revision source not found: {path}") from exc
    except OSError as exc:
        raise ValidationError(f"Unable to inspect revision source {path}: {exc}") from exc
    if stat.S_ISLNK(mode):
        raise UnsafeOperationError(f"Symbolic links are not allowed in revision sources: {path}")
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    raise ValidationError(f"Unsupported revision source filesystem object: {path}")


def _validate_name(name: str, path: Path) -> None:
    if not name or name in {".", ".."}:
        raise ValidationError(f"Unsafe revision source name: {path}")
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ValidationError(f"Control characters are not allowed in revision source names: {path}")
    if name.casefold() == _RESERVED_NAME:
        raise ValidationError(f"Revision source may not replace Revision_Notes.md: {path}")


def build_plan(source: Path) -> RevisionSourcePlan:
    source = source.expanduser()
    if not source.is_absolute():
        source = Path.cwd() / source
    source_type = _classify(source)
    source = source.resolve(strict=True)
    names: list[str] = []
    seen: dict[str, str] = {_RESERVED_NAME: "Revision_Notes.md"}

    def add_file(path: Path) -> None:
        _validate_name(path.name, path)
        if is_ignored_os_metadata_path(path):
            return
        key = path.name.casefold()
        if key in seen:
            raise ValidationError(
                f"Case-insensitive revision destination collision: {seen[key]!r} and {path.name!r}"
            )
        seen[key] = path.name
        names.append(path.name)

    if source_type == "file":
        add_file(source)
    else:
        try:
            children = sorted(os.scandir(source), key=lambda item: (item.name.casefold(), item.name))
        except OSError as exc:
            raise ValidationError(f"Unable to read revision source directory {source}: {exc}") from exc
        for child in children:
            child_path = Path(child.path)
            entry_type = _classify(child_path)
            if entry_type == "directory":
                raise ValidationError(f"Nested directories are not allowed in revision sources: {child_path}")
            add_file(child_path)

    names.sort(key=lambda value: (value.casefold(), value))
    return RevisionSourcePlan(source_type, source, tuple(names))


def copy_from_plan(plan: RevisionSourcePlan, destination: Path) -> None:
    current = build_plan(plan.source)
    if current.source_type != plan.source_type or current.files != plan.files:
        raise ValidationError("Revision source changed after preflight; no revision was created.")
    if destination.is_symlink() or not destination.is_dir():
        raise UnsafeOperationError(f"Revision destination is missing or unsafe: {destination}")
    if any(destination.iterdir()):
        raise UnsafeOperationError(f"Revision destination must be empty before source copying: {destination}")

    for name in current.files:
        source_file = plan.source if plan.source_type == "file" else plan.source / name
        shutil.copy2(source_file, destination / name, follow_symlinks=False)
