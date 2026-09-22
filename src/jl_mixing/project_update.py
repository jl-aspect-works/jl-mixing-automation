"""Authoritative project-manifest update service."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from .errors import ContextError, ValidationError
from .metadata import touch_document, validate_v11, write_json_document
from .project import _nonempty, _optional_text, _validate_bpm, _validate_deadline
from .validation import require_bit_depth, require_deliverables, require_file_format, require_sample_rate
from .versions import application_root

_AUDIO_FIELDS = {"audio.sample_rate", "audio.bit_depth", "audio.file_format"}
_DELIVERY_FIELDS = {"delivery.method", "delivery.requested_deliverables"}


@dataclass(frozen=True)
class ProjectUpdateRequest:
    project_root: Path
    project_name: str | None = None
    artist: str | None = None
    album: str | None = None
    producer: str | None = None
    mix_engineer: str | None = None
    bpm_set: bool = False
    bpm: float | int | None = None
    musical_key: str | None = None
    time_signature: str | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    file_format: str | None = None
    delivery_method: str | None = None
    requested_deliverables: tuple[str, ...] | None = None
    deadline_set: bool = False
    deadline: str | None = None
    creative_direction: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class ProjectUpdateResult:
    project_root: Path
    manifest_path: Path
    document: dict[str, Any]
    changed_fields: tuple[str, ...]
    invalidations: tuple[str, ...]
    committed: bool


def _schema() -> dict[str, Any]:
    path = application_root() / "schemas" / "project-manifest.schema.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextError(f"Required project schema is unreadable: {path}") from exc


def _validate(document: dict[str, Any]) -> None:
    validate_v11(document.get("metadata"), "mixing-project", mutability="mutable")
    try:
        jsonschema.Draft202012Validator(_schema()).validate(document)
    except jsonschema.ValidationError as exc:
        raise ValidationError(f"Project manifest failed schema validation: {exc.message}") from exc


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContextError(f"Project manifest not found or unsafe: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid project manifest: {path}") from exc
    if not isinstance(document, dict):
        raise ValidationError(f"Invalid project manifest object: {path}")
    _validate(document)
    return document


def update_project(request: ProjectUpdateRequest) -> ProjectUpdateResult:
    root = request.project_root.resolve()
    path = root / "00_Admin" / "project-manifest.json"
    original = _read(path)
    updated = deepcopy(original)
    changed: list[str] = []

    def assign(keys: tuple[str, ...], value: object, label: str) -> None:
        current: Any = updated
        for key in keys[:-1]:
            current = current[key]
        key = keys[-1]
        if current[key] != value:
            current[key] = value
            changed.append(label)

    if request.project_name is not None:
        assign(("project_name",), _nonempty(request.project_name, "project name"), "project_name")
    if request.artist is not None:
        assign(("artist",), _nonempty(request.artist, "Artist"), "artist")
    if request.album is not None:
        assign(("album",), _optional_text(request.album), "album")
    if request.producer is not None:
        assign(("producer",), _optional_text(request.producer), "producer")
    if request.mix_engineer is not None:
        assign(("mix_engineer",), _optional_text(request.mix_engineer), "mix_engineer")
    if request.bpm_set:
        assign(("music", "bpm"), _validate_bpm(request.bpm), "music.bpm")
    if request.musical_key is not None:
        assign(("music", "key"), _optional_text(request.musical_key), "music.key")
    if request.time_signature is not None:
        assign(("music", "time_signature"), _optional_text(request.time_signature), "music.time_signature")
    if request.sample_rate is not None:
        assign(("audio", "sample_rate"), require_sample_rate(request.sample_rate), "audio.sample_rate")
    if request.bit_depth is not None:
        assign(("audio", "bit_depth"), require_bit_depth(request.bit_depth), "audio.bit_depth")
    if request.file_format is not None:
        assign(("audio", "file_format"), require_file_format(request.file_format), "audio.file_format")
    if request.delivery_method is not None:
        assign(("delivery", "method"), _nonempty(request.delivery_method, "delivery method"), "delivery.method")
    if request.requested_deliverables is not None:
        assign(("delivery", "requested_deliverables"), require_deliverables(list(request.requested_deliverables)), "delivery.requested_deliverables")
    if request.deadline_set:
        assign(("schedule", "deadline"), _validate_deadline(request.deadline), "schedule.deadline")
    if request.creative_direction is not None:
        assign(("creative_direction",), _optional_text(request.creative_direction), "creative_direction")

    invalidations: list[str] = []
    if _AUDIO_FIELDS.intersection(changed):
        invalidations.extend(["intake.validation_context", "audio_prep.validation_context"])
    if _DELIVERY_FIELDS.intersection(changed):
        invalidations.append("delivery.readiness")

    if changed:
        updated = touch_document(updated)
    _validate(updated)
    if request.dry_run or not changed:
        return ProjectUpdateResult(root, path, updated, tuple(changed), tuple(invalidations), False)

    write_json_document(path, updated)
    committed = _read(path)
    if committed != updated:
        raise ValidationError("Committed project manifest did not verify after update.")
    return ProjectUpdateResult(root, path, committed, tuple(changed), tuple(invalidations), True)
