"""Plan and execute safe Original Delivery deletion with lineage reconciliation."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import uuid
from pathlib import Path

from .errors import UnsafeOperationError, ValidationError
from . import managed_client_files as files
from . import managed_client_file_provenance as lineage

ROOT = files.ORIGINAL_ROOT.as_posix()


class PartialCleanupError(RuntimeError):
    def __init__(self, path: Path, cause: Exception):
        super().__init__(f"Deletion cleanup is incomplete at {path}; inspect it before trying again: {cause}")
        self.path = path


def _selected(project: Path, relative_path: str) -> tuple[str, Path]:
    if not relative_path or "\\" in relative_path or any(part in {"", ".", ".."} for part in relative_path.split("/")):
        raise UnsafeOperationError("A safe project-relative path is required.")
    prefix = ROOT + "/"
    if not relative_path.startswith(prefix) or len(relative_path) <= len(prefix):
        raise UnsafeOperationError("Only content inside Original Delivery can be deleted; the managed folder is protected.")
    if any(part.startswith(".jl-mixing-deleting-") for part in relative_path.split("/")):
        raise UnsafeOperationError("Incomplete cleanup content requires manual review.")
    target = files._managed_destination(project, relative_path)
    try:
        mode = target.lstat().st_mode
    except FileNotFoundError as exc:
        raise ValidationError("The selected Original Delivery item is no longer available.") from exc
    if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        raise UnsafeOperationError("Symbolic links and special files cannot be deleted.")
    return relative_path, target


def _inventory(path: Path) -> tuple[list[tuple[str, os.stat_result, bool]], int, int, int]:
    items: list[tuple[str, os.stat_result, bool]] = []
    files_count = folders_count = total_bytes = 0

    def walk(current: Path) -> None:
        nonlocal files_count, folders_count, total_bytes
        info = current.lstat()
        regular, folder = stat.S_ISREG(info.st_mode), stat.S_ISDIR(info.st_mode)
        if not (regular or folder):
            raise UnsafeOperationError("The selected content contains a symbolic link or unsupported item.")
        items.append((current.relative_to(path).as_posix(), info, folder))
        if regular:
            files_count += 1
            total_bytes += info.st_size
        else:
            folders_count += 1
            for child in sorted(current.iterdir(), key=lambda item: item.name):
                walk(child)

    walk(path)
    return items, files_count, folders_count, total_bytes


def plan(project: Path, relative_path: str) -> dict[str, object]:
    relative, target = _selected(project, relative_path)
    items, file_count, directory_count, total_bytes = _inventory(target)
    admin = project / "00_Admin"
    if admin.is_symlink() or (admin.exists() and not admin.is_dir()):
        raise UnsafeOperationError("The managed metadata folder is unavailable or unsafe.")
    document = lineage._load(project)  # Raises on malformed or unsafe managed metadata.
    source = relative.removeprefix(ROOT + "/").casefold()
    is_directory = target.is_dir()
    linked = [entry for entry in document["entries"] if (value := str(entry["source_relative_path"]).casefold()) == source
              or (is_directory and value.startswith(source + "/"))]
    working_copies = sorted(str(entry["working_relative_path"]) for entry in linked)

    digest = hashlib.sha256()
    digest.update(relative.encode("utf-8"))
    for path, info, folder in items:
        digest.update(repr((path, folder, info.st_size, info.st_mtime_ns)).encode("utf-8"))
    digest.update(repr([(entry["source_relative_path"], entry["working_relative_path"]) for entry in document["entries"]]).encode("utf-8"))
    return {
        "relative_path": relative, "display_name": target.name, "is_directory": is_directory,
        "file_count": file_count, "directory_count": directory_count,
        "total_bytes": total_bytes, "fingerprint": digest.hexdigest(),
        "working_copies_retained": working_copies,
    }


def execute(project: Path, relative_path: str, fingerprint: str, confirm_name: str) -> dict[str, object]:
    summary = plan(project, relative_path)
    if fingerprint != summary["fingerprint"]:
        raise ValidationError("Original Delivery content or lineage changed; review a new deletion summary.")
    if confirm_name != summary["display_name"]:
        raise ValidationError("Confirmation must match the selected file or folder name exactly.")
    _, target = _selected(project, relative_path)
    document = lineage._load(project)
    source = relative_path.removeprefix(ROOT + "/").casefold()
    is_directory = bool(summary["is_directory"])
    entries = [entry for entry in document["entries"] if (value := str(entry["source_relative_path"]).casefold()) != source
               and not (is_directory and value.startswith(source + "/"))]

    staged = target.with_name(f".jl-mixing-deleting-{uuid.uuid4().hex}")
    target.rename(staged)
    try:
        if len(entries) != len(document["entries"]):
            document["entries"] = entries
            lineage._write(project, document)
    except Exception as exc:
        try:
            staged.rename(target)
        except OSError as rollback_error:
            raise PartialCleanupError(staged, rollback_error) from exc
        raise

    try:
        if is_directory:
            shutil.rmtree(staged)
        else:
            staged.unlink()
    except OSError as exc:
        raise PartialCleanupError(staged, exc) from exc
    return summary
