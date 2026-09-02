"""Cross-platform source-import planning and copy primitives."""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from .errors import UnsafeOperationError, ValidationError
from .filesystem_noise import is_filesystem_noise_name


@dataclass(frozen=True)
class SourceEntry:
    type: str
    path: str


@dataclass(frozen=True)
class SourcePlan:
    source_type: str
    source: Path
    entries: tuple[SourceEntry, ...]


def _validate_component(name: str, path: Path) -> None:
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ValidationError(f"Control characters are not allowed in source names: {path}")


def _classify(path: Path) -> str:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise ValidationError(f"Unable to inspect source path {path}: {exc}") from exc
    if stat.S_ISLNK(mode):
        raise UnsafeOperationError(f"Symbolic links are not allowed in source imports: {path}")
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    raise ValidationError(f"Unsupported source filesystem object: {path}")


def _absolute_without_following(path: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    return Path(os.path.abspath(expanded))


def build_plan(source: Path) -> SourcePlan:
    source = _absolute_without_following(source)
    source_type = _classify(source)
    # It is safe to canonicalize only after lstat() has rejected a top-level
    # symlink. Canonical paths keep containment comparisons stable on Windows.
    source = source.resolve(strict=True)
    entries: list[SourceEntry] = []
    seen: dict[str, str] = {}

    def add_entry(relative: Path, entry_type: str) -> None:
        display = relative.as_posix()
        key = display.casefold()
        if key in seen:
            raise ValidationError(
                f"Case-insensitive source-path collision: {seen[key]!r} and {display!r}"
            )
        seen[key] = display
        entries.append(SourceEntry(entry_type, display))

    if source_type == "file":
        _validate_component(source.name, source)
        if not is_filesystem_noise_name(source.name):
            add_entry(Path(source.name), "file")
    else:
        def walk(directory: Path, relative_directory: Path) -> None:
            try:
                children = sorted(os.scandir(directory), key=lambda item: (item.name.casefold(), item.name))
            except OSError as exc:
                raise ValidationError(f"Unable to read source directory {directory}: {exc}") from exc
            for child in children:
                child_path = Path(child.path)
                _validate_component(child.name, child_path)
                relative = relative_directory / child.name
                entry_type = _classify(child_path)
                if entry_type == "file" and is_filesystem_noise_name(child_path.name):
                    continue
                add_entry(relative, entry_type)
                if entry_type == "directory":
                    walk(child_path, relative)

        walk(source, Path())

    entries.sort(key=lambda item: (item.path.casefold(), item.path, item.type))
    return SourcePlan(source_type, source, tuple(entries))


def copy_from_plan(plan: SourcePlan, destination: Path) -> None:
    current = build_plan(plan.source)
    if current.source_type != plan.source_type or current.entries != plan.entries:
        raise ValidationError("Source import changed after preflight; no project was created.")
    if destination.is_symlink() or not destination.is_dir():
        raise UnsafeOperationError(f"Source-import destination is missing or unsafe: {destination}")
    if any(destination.iterdir()):
        raise UnsafeOperationError(f"Source-import destination must be empty: {destination}")

    directories = [entry for entry in plan.entries if entry.type == "directory"]
    files = [entry for entry in plan.entries if entry.type == "file"]
    for entry in sorted(directories, key=lambda value: (value.path.count("/"), value.path)):
        destination.joinpath(*Path(entry.path).parts).mkdir(parents=True, exist_ok=False)

    for entry in files:
        relative = Path(entry.path)
        source_file = plan.source if plan.source_type == "file" else plan.source / relative
        destination_file = destination / relative
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file, follow_symlinks=False)

    if plan.source_type == "directory":
        for entry in sorted(directories, key=lambda value: value.path.count("/"), reverse=True):
            relative = Path(entry.path)
            shutil.copystat(plan.source / relative, destination / relative, follow_symlinks=False)
