"""Authoritative studio configuration update service."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from .errors import ContextError, ValidationError
from .metadata import touch_document, validate_v11, write_json_document
from .validation import require_bit_depth, require_file_format, require_sample_rate
from .versions import application_root

_ALLOWED_DELIVERABLES = {
    "main_mix",
    "instrumental",
    "acapella",
    "tv_mix",
    "performance_mix",
    "stems",
    "master",
}


@dataclass(frozen=True)
class StudioUpdateRequest:
    studio_root: Path
    studio_name: str | None = None
    mix_engineer: str | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    file_format: str | None = None
    delivery_method: str | None = None
    requested_deliverables: tuple[str, ...] | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class StudioUpdateResult:
    studio_root: Path
    studio_config: Path
    document: dict[str, Any]
    changed_fields: tuple[str, ...]
    previous_last_modified_at: str
    committed: bool


def _schema() -> dict[str, Any]:
    schema_path = application_root() / "schemas" / "studio.schema.json"
    try:
        return json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextError(f"Required studio schema is unreadable: {schema_path}") from exc


def _validate_document(document: dict[str, Any]) -> None:
    validate_v11(document.get("metadata"), "mixing-studio", mutability="mutable")
    try:
        jsonschema.Draft202012Validator(_schema()).validate(document)
    except jsonschema.ValidationError as exc:
        raise ValidationError(f"Studio configuration failed schema validation: {exc.message}") from exc


def _read_config(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContextError(f"Studio configuration not found or unsafe: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid studio configuration: {path}") from exc
    if not isinstance(document, dict):
        raise ValidationError(f"Invalid studio configuration object: {path}")
    _validate_document(document)
    return document


def _validated_deliverables(values: tuple[str, ...]) -> list[str]:
    if not values:
        raise ValidationError("requested deliverables must contain at least one value.")
    normalized = [value.strip() for value in values]
    if any(not value for value in normalized):
        raise ValidationError("requested deliverables must not contain empty values.")
    if len(set(normalized)) != len(normalized):
        raise ValidationError("requested deliverables must not contain duplicates.")
    unsupported = [value for value in normalized if value not in _ALLOWED_DELIVERABLES]
    if unsupported:
        raise ValidationError(f"Unsupported requested deliverable: {unsupported[0]}")
    return normalized


def update_studio(request: StudioUpdateRequest) -> StudioUpdateResult:
    root = request.studio_root.resolve()
    config = root / "Studio" / "studio.json"
    original = _read_config(config)
    updated = deepcopy(original)
    changed: list[str] = []

    def assign(path: tuple[str, ...], value: object, label: str) -> None:
        current: Any = updated
        for key in path[:-1]:
            current = current[key]
        key = path[-1]
        if current[key] != value:
            current[key] = value
            changed.append(label)

    if request.studio_name is not None:
        name = request.studio_name.strip()
        if not name:
            raise ValidationError("studio name must not be empty.")
        assign(("studio_name",), name, "studio_name")
    if request.mix_engineer is not None:
        assign(("defaults", "mix_engineer"), request.mix_engineer.strip(), "defaults.mix_engineer")
    if request.sample_rate is not None:
        assign(("defaults", "audio", "sample_rate"), require_sample_rate(request.sample_rate), "defaults.audio.sample_rate")
    if request.bit_depth is not None:
        assign(("defaults", "audio", "bit_depth"), require_bit_depth(request.bit_depth), "defaults.audio.bit_depth")
    if request.file_format is not None:
        assign(("defaults", "audio", "file_format"), require_file_format(request.file_format), "defaults.audio.file_format")
    if request.delivery_method is not None:
        method = request.delivery_method.strip()
        if not method:
            raise ValidationError("delivery method must not be empty.")
        assign(("defaults", "delivery", "method"), method, "defaults.delivery.method")
    if request.requested_deliverables is not None:
        assign(
            ("defaults", "delivery", "requested_deliverables"),
            _validated_deliverables(request.requested_deliverables),
            "defaults.delivery.requested_deliverables",
        )

    previous_modified = str(original["metadata"]["last_modified_at"])
    if changed:
        updated = touch_document(updated)
    _validate_document(updated)

    if request.dry_run or not changed:
        return StudioUpdateResult(root, config, updated, tuple(changed), previous_modified, False)

    write_json_document(config, updated)
    committed = _read_config(config)
    if committed != updated:
        raise ValidationError("Committed studio configuration did not verify after update.")
    return StudioUpdateResult(root, config, committed, tuple(changed), previous_modified, True)
