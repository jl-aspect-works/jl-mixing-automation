"""Cross-platform staged transaction primitives."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from .errors import JLMixingError
from .paths import assert_mutable_path


def _fail_requested(point: str) -> bool:
    configured = os.environ.get("JL_MIXING_FAIL_AT", "")
    return any(item.strip() == point for item in configured.split(",") if item.strip())


def _injected_failure(point: str) -> JLMixingError:
    return JLMixingError(f"Injected transaction failure at: {point}")


def create_staging_directory(parent: Path, prefix: str) -> Path:
    """Create a unique sibling staging directory using normal ACL inheritance.

    Python's private temporary-directory helper intentionally creates directories
    with restrictive permissions. On SMB/NAS shares that can translate into a
    server ACL that prevents the Windows client from creating children or
    deleting the stage. A normal mkdir keeps the parent's ordinary inheritance
    behavior while the randomized hidden name still provides collision-safe
    transaction staging.
    """

    if parent.is_symlink() or not parent.is_dir():
        raise JLMixingError(f"Staging parent is missing or unsafe: {parent}")

    for _ in range(32):
        candidate = parent / f"{prefix}{uuid.uuid4().hex[:12]}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        except OSError as exc:
            raise JLMixingError(f"Could not create staging directory in {parent}: {exc}") from exc
        return candidate

    raise JLMixingError(f"Could not allocate a unique staging directory in {parent}")


def create_staging_file(parent: Path, prefix: str) -> tuple[int, Path]:
    """Create an exclusive sibling file using normal ACL inheritance."""

    if parent.is_symlink() or not parent.is_dir():
        raise JLMixingError(f"Staging parent is missing or unsafe: {parent}")

    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    for _ in range(32):
        candidate = parent / f"{prefix}{uuid.uuid4().hex[:12]}"
        try:
            fd = os.open(candidate, flags, 0o666)
        except FileExistsError:
            continue
        except OSError as exc:
            raise JLMixingError(f"Could not create staging file in {parent}: {exc}") from exc
        return fd, candidate

    raise JLMixingError(f"Could not allocate a unique staging file in {parent}")


def reserve_staging_path(parent: Path, prefix: str) -> Path:
    """Return a unique absent sibling path without creating restrictive metadata."""

    if parent.is_symlink() or not parent.is_dir():
        raise JLMixingError(f"Staging parent is missing or unsafe: {parent}")
    for _ in range(32):
        candidate = parent / f"{prefix}{uuid.uuid4().hex[:12]}"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise JLMixingError(f"Could not allocate a unique staging path in {parent}")


def commit_new_directory(staged_directory: Path, destination: Path) -> None:
    """Commit a staged directory that must not already exist.

    Preserves the v1.4 ``before-directory-commit`` and
    ``after-directory-commit`` failure-injection contract. A failure after the
    rename removes only the directory created by this transaction.

    The destination is required not to exist, so use ordinary rename semantics
    rather than replacement semantics. This is equivalent on POSIX and avoids
    Windows/SMB providers that reject directory replacement even when the
    destination is absent.
    """

    if staged_directory.is_symlink() or not staged_directory.is_dir():
        raise JLMixingError(f"Staged directory is missing or unsafe: {staged_directory}")
    if destination.exists() or destination.is_symlink():
        raise JLMixingError(f"Transaction destination already exists: {destination}")
    if _fail_requested("before-directory-commit"):
        raise _injected_failure("before-directory-commit")

    committed = False
    try:
        try:
            os.rename(staged_directory, destination)
        except OSError as exc:
            raise JLMixingError(
                f"Could not commit staged directory to {destination}: {exc}"
            ) from exc
        committed = True
        if _fail_requested("after-directory-commit"):
            raise _injected_failure("after-directory-commit")
    except Exception:
        if committed and (destination.exists() or destination.is_symlink()):
            if destination.is_symlink() or destination.is_file():
                destination.unlink()
            elif destination.is_dir():
                shutil.rmtree(destination, ignore_errors=True)
        raise


def _write_sibling(path: Path, data: bytes, mode: int | None) -> Path:
    fd, temp_path = create_staging_file(path.parent, f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temp_path, mode)
        return temp_path
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def atomic_write_bytes(target: Path, data: bytes, *, mode: int | None = None) -> None:
    """Atomically replace one file with rollback-compatible test hooks.

    The prior regular file is retained in memory until replacement succeeds so
    the v1.4 ``after-file-backup`` and ``after-file-replacement`` failure
    injection points can exercise the same rollback contract on every platform.
    Production behavior is unchanged when ``JL_MIXING_FAIL_AT`` is unset.
    """

    assert_mutable_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    prior_exists = target.exists()
    prior_data: bytes | None = None
    prior_mode: int | None = None
    if prior_exists:
        if target.is_symlink() or not target.is_file():
            raise JLMixingError(f"Transaction file target is missing or unsafe: {target}")
        prior_data = target.read_bytes()
        prior_mode = target.stat().st_mode & 0o777

    if _fail_requested("after-file-backup"):
        raise _injected_failure("after-file-backup")

    final_mode = mode if mode is not None else prior_mode
    temp_path = _write_sibling(target, data, final_mode)
    replaced = False
    try:
        os.replace(temp_path, target)
        replaced = True
        if _fail_requested("after-file-replacement"):
            raise _injected_failure("after-file-replacement")
    except Exception:
        if replaced:
            if prior_exists:
                assert prior_data is not None
                restore = _write_sibling(target, prior_data, prior_mode)
                try:
                    os.replace(restore, target)
                finally:
                    if restore.exists():
                        restore.unlink()
            elif target.exists() or target.is_symlink():
                target.unlink()
        raise
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_write_text(
    target: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    newline: str = "\n",
    mode: int | None = None,
) -> None:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if newline != "\n":
        normalized = normalized.replace("\n", newline)
    atomic_write_bytes(target, normalized.encode(encoding), mode=mode)
