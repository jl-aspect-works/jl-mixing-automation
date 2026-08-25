#!/usr/bin/env python3
"""Validate, install, or remove the JL Mixing managed shell block.

The helper works with bytes so user-authored startup-file content outside the
managed block is preserved exactly. It deliberately refuses duplicate,
reversed, partial, or non-line-aligned markers rather than guessing how to
repair a user's shell configuration.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import os
import sys


def _create_staging_file(path: Path) -> tuple[int, Path]:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    for _ in range(32):
        candidate = path.parent / f".{path.name}.jl-mixing.{os.urandom(6).hex()}"
        try:
            return os.open(candidate, flags, 0o666), candidate
        except FileExistsError:
            continue
    raise RuntimeError(f"could not allocate staging file beside {path}")

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


def remove_block(data: bytes, *, require_present: bool) -> bytes:
    span = locate_block(data)
    if span is None:
        if require_present:
            raise MarkerError("managed shell block is not present")
        return data
    before = data[: span[0]]
    after = data[span[1] :]
    # Remove one separator newline introduced solely to append the block while
    # preserving all other bytes. This keeps an otherwise empty startup file
    # empty after uninstall.
    if not before.strip() and not after.strip():
        return b""
    return before + after


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, temporary = _create_staging_file(path)
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


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("file")

    install = subparsers.add_parser("install")
    install.add_argument("file")
    install.add_argument("--block-file", required=True)
    install.add_argument("--output")

    remove = subparsers.add_parser("remove")
    remove.add_argument("file")
    remove.add_argument("--output")
    remove.add_argument("--require-present", action="store_true")

    args = parser.parse_args()
    target = Path(args.file)
    data = target.read_bytes() if target.exists() else b""

    try:
        if args.command == "validate":
            span = locate_block(data)
            print("present" if span is not None else "absent")
            return 0
        if args.command == "install":
            block = Path(args.block_file).read_bytes()
            result = install_block(data, block)
        else:
            result = remove_block(data, require_present=args.require_present)
    except MarkerError as exc:
        print(f"Error: {exc}: {target}", file=sys.stderr)
        return 5

    output = Path(args.output) if args.output else target
    atomic_write(output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
