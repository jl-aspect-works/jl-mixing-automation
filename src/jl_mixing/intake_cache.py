"""Persistent helpers for incremental intake validation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

CACHE_SCHEMA_VERSION = 1
_FINGERPRINT_CHUNK_SIZE = 64 * 1024


def content_fingerprint(path: Path, *, size: int | None = None) -> str:
    """Return a cheap content fingerprint that is stronger than metadata alone."""
    if size is None:
        size = path.stat().st_size
    digest = hashlib.sha256()
    digest.update(str(size).encode("ascii"))
    with path.open("rb") as handle:
        digest.update(handle.read(_FINGERPRINT_CHUNK_SIZE))
        if size > _FINGERPRINT_CHUNK_SIZE:
            handle.seek(max(0, size - _FINGERPRINT_CHUNK_SIZE))
            digest.update(handle.read(_FINGERPRINT_CHUNK_SIZE))
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_cache(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file() or path.is_symlink():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(document, dict) or document.get("schema_version") != CACHE_SCHEMA_VERSION:
        return {}
    files = document.get("files")
    if not isinstance(files, dict):
        return {}
    return {str(key): value for key, value in files.items() if isinstance(value, dict)}


def reusable_cache_record(
    path: Path,
    relative_path: str,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    record = cache.get(relative_path)
    if not isinstance(record, dict):
        return None
    stat = path.stat()
    if record.get("size_bytes") != stat.st_size or record.get("modified_ns") != stat.st_mtime_ns:
        return None
    try:
        fingerprint = content_fingerprint(path, size=stat.st_size)
    except OSError:
        return None
    if record.get("fingerprint") != fingerprint:
        return None
    return record


def cache_identity(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "size_bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
        "fingerprint": content_fingerprint(path, size=stat.st_size),
    }


def write_cache(path: Path | None, records: dict[str, dict[str, Any]]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "files": records,
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
