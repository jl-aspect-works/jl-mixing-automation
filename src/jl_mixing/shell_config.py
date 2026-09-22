"""Managed shell configuration primitives shared by installers."""

from __future__ import annotations

import os
from pathlib import Path

from .transactions import create_staging_file

BEGIN = b"# >>> JL Mixing managed configuration >>>"
END = b"# <<< JL Mixing managed configuration <<<"


class MarkerError(ValueError):
    pass


def _line_spans(data: bytes) -> list[tuple[int, int, bytes]]:
    spans: list[tuple[int, int, bytes]] = []
    offset = 0
    for line in data.splitlines(keepends=True):
        end = offset + len(line)
        spans.append((offset, end, line.rstrip(b"\r\n")))
        offset = end
    if offset < len(data):
        spans.append((offset, len(data), data[offset:]))
    return spans


def locate_block(data: bytes) -> tuple[int, int] | None:
    begin_count = data.count(BEGIN)
    end_count = data.count(END)
    if begin_count == 0 and end_count == 0:
        return None
    if begin_count != 1 or end_count != 1:
        raise MarkerError("managed shell markers are missing or duplicated")

    begin_span: tuple[int, int] | None = None
    end_span: tuple[int, int] | None = None
    for start, end, content in _line_spans(data):
        if BEGIN in content and content != BEGIN:
            raise MarkerError("opening managed marker is not on its own line")
        if END in content and content != END:
            raise MarkerError("closing managed marker is not on its own line")
        if content == BEGIN:
            begin_span = (start, end)
        elif content == END:
            end_span = (start, end)

    if begin_span is None or end_span is None:
        raise MarkerError("managed shell markers are malformed")
    if begin_span[0] >= end_span[0]:
        raise MarkerError("managed shell markers are reversed")
    return begin_span[0], end_span[1]


def install_block(data: bytes, block: bytes) -> bytes:
    span = locate_block(data)
    normalized = block.rstrip(b"\r\n") + b"\n"
    if span is not None:
        return data[: span[0]] + normalized + data[span[1] :]
    if not data:
        return normalized
    separator = b"" if data.endswith((b"\n", b"\r")) else b"\n"
    return data + separator + normalized


def remove_block(data: bytes, *, require_present: bool = False) -> bytes:
    span = locate_block(data)
    if span is None:
        if require_present:
            raise MarkerError("managed shell block is not present")
        return data
    before = data[: span[0]]
    after = data[span[1] :]
    if not before.strip() and not after.strip():
        return b""
    return before + after


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, temporary = create_staging_file(path.parent, f".{path.name}.jl-mixing.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
