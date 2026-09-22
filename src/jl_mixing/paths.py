"""Cross-platform path and filesystem safety primitives."""

from __future__ import annotations

import os
import shutil
from pathlib import Path, PurePosixPath

from .errors import UnsafeOperationError, ValidationError

_ORIGINAL_DELIVERY_PARTS = ("01_Client_Files", "Original_Delivery")
_DAW_PROJECT_PART = "03_DAW_Project"


def portable_relative_path(value: str) -> PurePosixPath:
    """Validate a manifest-relative path using the v1.4 portable grammar."""

    if not value or value.startswith("/") or "\\" in value:
        raise ValidationError(f"Unsafe relative path: {value}")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValidationError(f"Unsafe relative path segments in: {value}")
    return PurePosixPath(*parts)


def native_absolute_path(value: str | os.PathLike[str], *, base: Path | None = None) -> Path:
    """Resolve a native path without imposing POSIX lexical rules on Windows."""

    path = Path(value).expanduser()
    if not path.is_absolute():
        if base is None:
            raise ValidationError(f"Absolute path required: {value}")
        path = Path(base) / path
    return path.resolve(strict=False)


def resolve_under_root(root: Path, relative: str) -> Path:
    """Resolve a validated portable relative path beneath a native root."""

    root = native_absolute_path(root)
    rel = portable_relative_path(relative)
    candidate = root.joinpath(*rel.parts).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafeOperationError(f"Resolved path escapes root '{root}': {relative}") from exc
    return candidate


def _contains_subsequence(parts: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    width = len(needle)
    return any(parts[index : index + width] == needle for index in range(len(parts) - width + 1))


def is_original_delivery_path(path: Path | str) -> bool:
    parts = native_absolute_path(path, base=Path.cwd()).parts
    return _contains_subsequence(parts, _ORIGINAL_DELIVERY_PARTS)


def is_daw_project_path(path: Path | str) -> bool:
    return _DAW_PROJECT_PART in native_absolute_path(path, base=Path.cwd()).parts


def assert_mutable_path(path: Path | str) -> None:
    if is_original_delivery_path(path):
        raise UnsafeOperationError(
            f"Unsafe operation prevented inside immutable Original_Delivery: {path}"
        )


def assert_automation_owned_path(path: Path | str) -> None:
    assert_mutable_path(path)
    if is_daw_project_path(path):
        raise UnsafeOperationError(
            f"Unsafe operation prevented inside opaque 03_DAW_Project: {path}"
        )


def find_case_insensitive_child_collision(parent: Path, proposed: str) -> Path | None:
    if not parent.is_dir():
        return None
    wanted = proposed.casefold()
    for child in parent.iterdir():
        if child.name.casefold() == wanted:
            return child
    return None


def assert_no_case_insensitive_child_collision(parent: Path, proposed: str) -> None:
    collision = find_case_insensitive_child_collision(parent, proposed)
    if collision is not None:
        raise ValidationError(f"Case-insensitive path collision: {collision}")


def assert_no_symlink_components(root: Path, destination: Path) -> None:
    """Reject symlinks from root through the existing destination components."""

    if root.is_symlink():
        raise UnsafeOperationError(f"Symlink root is not allowed: {root}")
    root = root.resolve(strict=True)
    destination = native_absolute_path(destination)
    try:
        relative = destination.relative_to(root)
    except ValueError as exc:
        raise UnsafeOperationError(f"Path escapes root: {destination}") from exc

    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise UnsafeOperationError(f"Symbolic-link path component is not allowed: {current}")
        if not current.exists():
            break


def ensure_directory(path: Path) -> None:
    if path.exists() and not path.is_dir():
        raise UnsafeOperationError(f"Cannot create directory because a non-directory exists: {path}")
    path.mkdir(parents=True, exist_ok=True)


def create_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise UnsafeOperationError(f"Refusing to overwrite existing path: {path}")
    path.mkdir(parents=True)


def copy_file_exact(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise ValidationError(f"Source file not found or unsafe: {source}")
    assert_mutable_path(destination)
    if destination.exists() or destination.is_symlink():
        raise UnsafeOperationError(f"Refusing to overwrite existing destination: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def remove_entry_no_follow(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        raise UnsafeOperationError(f"Unsupported filesystem entry cannot be removed safely: {path}")
