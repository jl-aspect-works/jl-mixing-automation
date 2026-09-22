"""Managed Markdown section helpers shared by report workflows."""

from __future__ import annotations

from pathlib import Path

from .errors import ValidationError
from .transactions import atomic_write_text


def replace_managed_section(path: Path, begin: str, end: str, replacement: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValidationError(f"Markdown file not found or unsafe: {path}")
    text = path.read_text(encoding="utf-8")
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValidationError(f"Managed Markdown markers are missing or duplicated: {path}")
    before, remainder = text.split(begin, 1)
    managed, after = remainder.split(end, 1)
    del managed
    content = replacement.rstrip("\n")
    updated = f"{before}{begin}\n{content}\n{end}{after}"
    atomic_write_text(path, updated)
