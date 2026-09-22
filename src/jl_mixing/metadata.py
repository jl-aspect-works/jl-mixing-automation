"""Cross-platform metadata creation, validation, and mutation."""

from __future__ import annotations

import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .errors import ArgumentError, ValidationError
from .transactions import atomic_write_text
from .versions import application_version

_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def now_iso8601() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def created_with() -> str:
    return f"jl-mixing {application_version()}"


def validate_created_with(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("jl-mixing "):
        raise ValidationError(f"Invalid created_with value: {value}")
    version = value.removeprefix("jl-mixing ")
    if not _SEMVER.fullmatch(version):
        raise ValidationError(f"Invalid jl-mixing semantic version: {version}")
    return value


def create_v11(
    schema: str,
    *,
    mutability: Literal["mutable", "immutable"],
    schema_version: str = "1.1.0",
    document_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, str]:
    if mutability not in {"mutable", "immutable"}:
        raise ArgumentError(f"Unknown metadata mutability: {mutability}")
    timestamp = timestamp or now_iso8601()
    metadata = {
        "schema": schema,
        "schema_version": schema_version,
        "document_id": document_id or str(uuid.uuid4()),
        "created_with": created_with(),
        "created_at": timestamp,
    }
    if mutability == "mutable":
        metadata["last_modified_at"] = timestamp
    return metadata


def validate_v11(
    metadata: object,
    expected_schema: str,
    *,
    mutability: Literal["mutable", "immutable"],
) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ValidationError("Missing metadata object")
    if metadata.get("schema") != expected_schema or metadata.get("schema_version") != "1.1.0":
        raise ValidationError(f"Unexpected metadata schema identity: {metadata.get('schema')} {metadata.get('schema_version')}")
    for field in ("document_id", "created_with", "created_at"):
        if not isinstance(metadata.get(field), str) or not metadata[field]:
            raise ValidationError(f"Missing metadata field: {field}")
    validate_created_with(metadata["created_with"])
    if "created_by" in metadata:
        raise ValidationError("v1.1 metadata must not contain created_by")
    if mutability == "mutable":
        if not isinstance(metadata.get("last_modified_at"), str) or not metadata["last_modified_at"]:
            raise ValidationError("Missing metadata field: last_modified_at")
    elif mutability == "immutable":
        if "last_modified_at" in metadata:
            raise ValidationError("Immutable metadata must not contain last_modified_at")
    else:
        raise ArgumentError(f"Unknown metadata mutability: {mutability}")
    return metadata


def touch_document(document: dict[str, Any], timestamp: str | None = None) -> dict[str, Any]:
    updated = deepcopy(document)
    metadata = updated.get("metadata")
    if not isinstance(metadata, dict):
        raise ValidationError("Missing metadata object")
    metadata["last_modified_at"] = timestamp or now_iso8601()
    return updated


def write_json_document(path: Path, document: dict[str, Any]) -> None:
    import json

    atomic_write_text(path, json.dumps(document, indent=2, ensure_ascii=False) + "\n")
