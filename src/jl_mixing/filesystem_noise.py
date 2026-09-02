"""Classification for OS-generated filesystem metadata that is not project content."""

from __future__ import annotations

from pathlib import PurePath, PurePosixPath

_EXACT_NOISE_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}


def is_filesystem_noise_name(name: str) -> bool:
    """Return whether one basename is a known OS-generated metadata artifact."""
    folded = name.casefold()
    return folded in _EXACT_NOISE_NAMES or folded.startswith("._")


def path_contains_filesystem_noise(path: str | PurePath) -> bool:
    """Return whether any component of a relative path is known filesystem noise."""
    if isinstance(path, PurePath):
        parts = path.parts
    else:
        parts = PurePosixPath(path.replace("\\", "/")).parts
    return any(is_filesystem_noise_name(part) for part in parts)
