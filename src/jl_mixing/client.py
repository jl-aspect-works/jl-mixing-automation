"""Authoritative cross-platform client creation service."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ContextError, UnsafeOperationError, ValidationError
from .metadata import create_v11
from .naming import sanitize_folder_name, title_from_slug
from .paths import assert_no_case_insensitive_child_collision, assert_no_symlink_components
from .transactions import commit_new_directory, create_staging_directory
from .validation import (
    require_bit_depth,
    require_deliverables,
    require_file_format,
    require_sample_rate,
    require_slug,
)


@dataclass(frozen=True)
class ClientCreateRequest:
    studio_root: Path
    client_id: str
    client_name: str | None = None
    artist: str = ""
    sample_rate: int | None = None
    bit_depth: int | None = None
    file_format: str | None = None
    delivery_method: str | None = None
    deliverables: list[str] | None = None
    change_directory: bool | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class ClientCreateResult:
    client_root: Path
    client_document: dict[str, Any]
    effective_cd: bool
    created: bool


def _load_studio(studio_root: Path) -> dict[str, Any]:
    studio_file = studio_root / "Studio" / "studio.json"
    if studio_root.is_symlink() or studio_file.is_symlink() or not studio_file.is_file():
        raise ContextError(f"Studio configuration not found or unsafe: {studio_file}")
    try:
        document = json.loads(studio_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid studio configuration: {studio_file}") from exc
    metadata = document.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("schema") != "mixing-studio" or metadata.get("schema_version") != "1.1.0":
        raise ValidationError(f"Unexpected studio schema identity: {studio_file}")
    return document


def _client_id_available(clients_root: Path, candidate: str) -> None:
    wanted = candidate.casefold()
    for client_file in clients_root.glob("*/client.json"):
        if client_file.is_symlink() or not client_file.is_file():
            continue
        try:
            existing = json.loads(client_file.read_text(encoding="utf-8")).get("client_id")
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(existing, str) and existing.casefold() == wanted:
            raise ValidationError(f"Client ID already exists: {candidate}")


def _require_nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must not be empty.")
    return value.strip()


def _build_document(request: ClientCreateRequest, studio: dict[str, Any]) -> tuple[dict[str, Any], str, bool]:
    client_id = require_slug(request.client_id, label="Client ID")
    client_name = (request.client_name if request.client_name is not None else title_from_slug(client_id)).strip()
    client_name = _require_nonempty(client_name, "client name")
    artist = request.artist.strip()

    defaults = studio.get("defaults") if isinstance(studio.get("defaults"), dict) else {}
    audio_defaults = defaults.get("audio") if isinstance(defaults.get("audio"), dict) else {}
    delivery_defaults = defaults.get("delivery") if isinstance(defaults.get("delivery"), dict) else {}

    sample_rate = require_sample_rate(request.sample_rate if request.sample_rate is not None else audio_defaults.get("sample_rate"))
    bit_depth = require_bit_depth(request.bit_depth if request.bit_depth is not None else audio_defaults.get("bit_depth"))
    file_format = require_file_format(request.file_format if request.file_format is not None else audio_defaults.get("file_format"))
    delivery_method = _require_nonempty(
        request.delivery_method if request.delivery_method is not None else delivery_defaults.get("method"),
        "delivery method",
    )
    deliverables_source = request.deliverables if request.deliverables is not None else delivery_defaults.get("requested_deliverables")
    deliverables = require_deliverables(deliverables_source)

    cli = studio.get("cli") if isinstance(studio.get("cli"), dict) else {}
    inherited_cd = cli.get("change_directory_after_create") is True
    effective_cd = request.change_directory if request.change_directory is not None else inherited_cd

    document: dict[str, Any] = {
        "metadata": create_v11("mixing-client", mutability="mutable"),
        "client_id": client_id,
        "client_name": client_name,
        "defaults": {
            "artist": artist,
            "audio": {
                "sample_rate": sample_rate,
                "bit_depth": bit_depth,
                "file_format": file_format,
            },
            "delivery": {
                "method": delivery_method,
                "requested_deliverables": deliverables,
            },
        },
    }
    return document, sanitize_folder_name(client_name), effective_cd


def create_client(request: ClientCreateRequest) -> ClientCreateResult:
    studio_root = request.studio_root.expanduser().resolve()
    studio = _load_studio(studio_root)
    clients_root = studio_root / "Clients"
    if clients_root.is_symlink() or not clients_root.is_dir():
        raise ContextError(f"Clients directory is missing or unsafe: {clients_root}")
    assert_no_symlink_components(studio_root, clients_root)

    document, folder_name, effective_cd = _build_document(request, studio)
    _client_id_available(clients_root, request.client_id)
    assert_no_case_insensitive_child_collision(clients_root, folder_name)
    destination = clients_root / folder_name
    if destination.exists() or destination.is_symlink():
        raise UnsafeOperationError(f"Client destination already exists: {destination}")

    if request.dry_run:
        return ClientCreateResult(destination, document, effective_cd, False)

    stage = create_staging_directory(clients_root, f".{folder_name}.jl-stage-")
    try:
        (stage / "Projects").mkdir()
        (stage / "client.json").write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if destination.exists() or destination.is_symlink():
            raise UnsafeOperationError(f"Client destination already exists: {destination}")
        commit_new_directory(stage, destination)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise

    return ClientCreateResult(destination, document, effective_cd, True)
