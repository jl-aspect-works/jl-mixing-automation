"""Shared v1.4-compatible validation rules."""

from __future__ import annotations

import re

from .errors import ValidationError

SUPPORTED_SAMPLE_RATES = frozenset({44100, 48000, 88200, 96000, 176400, 192000})
SUPPORTED_BIT_DEPTHS = frozenset({16, 24, 32})
SUPPORTED_FILE_FORMATS = frozenset({"WAV", "AIFF"})
SUPPORTED_DELIVERABLES = frozenset({
    "main_mix",
    "instrumental",
    "acapella",
    "tv_mix",
    "performance_mix",
    "stems",
    "master",
})
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def require_sample_rate(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value not in SUPPORTED_SAMPLE_RATES:
        raise ValidationError(f"Unsupported expected sample rate: {value}")
    return value


def require_bit_depth(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value not in SUPPORTED_BIT_DEPTHS:
        raise ValidationError(f"Unsupported expected bit depth: {value}")
    return value


def require_file_format(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"Unsupported file format: {value}")
    normalized = value.upper()
    if normalized not in SUPPORTED_FILE_FORMATS:
        raise ValidationError(f"Unsupported file format: {normalized}")
    return normalized


def require_slug(value: object, *, label: str = "ID") -> str:
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        raise ValidationError(f"{label} must be a lowercase slug using single hyphens: {value}")
    return value


def require_deliverables(values: object) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ValidationError("At least one requested deliverable is required.")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or value not in SUPPORTED_DELIVERABLES:
            raise ValidationError(f"Unsupported deliverable type: {value}")
        if value in seen:
            raise ValidationError("Requested deliverables must be unique.")
        seen.add(value)
        result.append(value)
    return result
