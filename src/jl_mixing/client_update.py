"""Authoritative client profile update service."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from .errors import ContextError, ValidationError
from .metadata import touch_document, validate_v11, write_json_document
from .validation import require_bit_depth, require_deliverables, require_file_format, require_sample_rate
from .versions import application_root


@dataclass(frozen=True)
class ClientUpdateRequest:
    client_root: Path
    client_name: str | None = None
    artist: str | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    file_format: str | None = None
    delivery_method: str | None = None
    requested_deliverables: tuple[str, ...] | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class ClientUpdateResult:
    client_root: Path
    client_config: Path
    document: dict[str, Any]
    changed_fields: tuple[str, ...]
    committed: bool


def _schema() -> dict[str, Any]:
    schema_path = application_root() / "schemas" / "client.schema.json"
    try:
        return json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextError(f"Required client schema is unreadable: {schema_path}") from exc


def _validate_document(document: dict[str, Any]) -> None:
    validate_v11(document.get("metadata"), "mixing-client", mutability="mutable")
    try:
        jsonschema.Draft202012Validator(_schema()).validate(document)
    except jsonschema.ValidationError as exc:
        raise ValidationError(f"Client profile failed schema validation: {exc.message}") from exc


def _read_config(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContextError(f"Client profile not found or unsafe: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid client profile: {path}") from exc
    if not isinstance(document, dict):
        raise ValidationError(f"Invalid client profile object: {path}")
    _validate_document(document)
    return document


def update_client(request: ClientUpdateRequest) -> ClientUpdateResult:
    root = request.client_root.resolve()
    config = root / "client.json"
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

    if request.client_name is not None:
        name = request.client_name.strip()
        if not name:
            raise ValidationError("client name must not be empty.")
        assign(("client_name",), name, "client_name")
    if request.artist is not None:
        assign(("defaults", "artist"), request.artist.strip(), "defaults.artist")
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
        deliverables = require_deliverables(list(request.requested_deliverables))
        assign(("defaults", "delivery", "requested_deliverables"), deliverables, "defaults.delivery.requested_deliverables")

    if changed:
        updated = touch_document(updated)
    _validate_document(updated)

    if request.dry_run or not changed:
        return ClientUpdateResult(root, config, updated, tuple(changed), False)

    write_json_document(config, updated)
    committed = _read_config(config)
    if committed != updated:
        raise ValidationError("Committed client profile did not verify after update.")
    return ClientUpdateResult(root, config, committed, tuple(changed), True)
