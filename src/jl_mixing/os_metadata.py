"""Platform-neutral filtering for operating-system-generated metadata files."""

from __future__ import annotations

from pathlib import Path, PurePath


def is_ignored_os_metadata_name(name: str) -> bool:
    """Return whether *name* is OS metadata, regardless of the current platform."""
    folded = name.casefold()
    return (
        name == ".DS_Store"
        or name.startswith("._")
        or folded == "thumbs.db"
        or folded == "desktop.ini"
    )


def is_ignored_os_metadata_path(path: Path | PurePath) -> bool:
    return is_ignored_os_metadata_name(path.name)
