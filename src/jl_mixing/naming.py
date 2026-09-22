"""Cross-platform naming helpers used by creation workflows."""

from __future__ import annotations

import re
import unicodedata

from .errors import ValidationError

_RESERVED = {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
_RESERVED.update({f"COM{i}" for i in range(1, 10)})
_RESERVED.update({f"LPT{i}" for i in range(1, 10)})


def title_from_slug(slug: str) -> str:
    return " ".join(part[:1].upper() + part[1:] for part in slug.split("-"))


def slugify(value: str) -> str:
    """Derive the v1.4-compatible lowercase ASCII project/client slug."""

    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    if not slug:
        raise ValidationError("Project name does not produce a usable project ID.")
    return slug


def sanitize_folder_name(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    characters: list[str] = []
    for character in value:
        if ord(character) < 32 or ord(character) == 127:
            characters.append(" ")
        elif character in '/\\:*?"<>|':
            characters.append(" - ")
        else:
            characters.append(character)
    result = "".join(characters)
    result = re.sub(r"\s+", " ", result).strip()
    result = re.sub(r"(?:\s*-\s*)+", " - ", result).strip()
    result = result.strip(" .-")
    if not result:
        raise ValidationError("Display name does not produce a usable folder name.")
    base = result.split(".", 1)[0].upper()
    if result in {".", ".."} or base in _RESERVED:
        raise ValidationError(f"Reserved folder name is not allowed: {result}")
    return result
