"""Authoritative cross-platform studio workspace creation service."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from .errors import ContextError, UnsafeOperationError, ValidationError
from .metadata import create_v11, validate_v11
from .naming import slugify
from .paths import assert_no_symlink_components
from .transactions import commit_new_directory, create_staging_directory
from .validation import require_bit_depth, require_file_format, require_sample_rate, require_slug
from .versions import application_root


@dataclass(frozen=True)
class StudioCreateRequest:
    root: Path
    name: str = "Mixing Studio"
    engineer: str = ""
    sample_rate: int = 48000
    bit_depth: int = 24
    file_format: str = "WAV"
    default_cd: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class StudioCreateResult:
    root: Path
    studio_config: Path
    document: dict[str, Any]
    created: bool


def _native_lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _validate_schema(document: dict[str, Any]) -> None:
    schema_path = application_root() / "schemas" / "studio.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(document)
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextError(f"Required studio schema is unreadable: {schema_path}") from exc
    except jsonschema.ValidationError as exc:
        raise ValidationError(f"Generated studio configuration failed schema validation: {exc.message}") from exc


def create_studio(request: StudioCreateRequest) -> StudioCreateResult:
    root = _native_lexical_absolute(request.root)
    if root.parent == root:
        raise UnsafeOperationError("The filesystem root cannot be used as a studio workspace.")
    if root.exists() or root.is_symlink():
        raise UnsafeOperationError(f"Studio root already exists: {root}")

    parent = root.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ContextError(f"Studio root parent must be an existing directory: {parent}")
    anchor = Path(root.anchor)
    if not anchor.exists():
        raise ContextError(f"Studio root anchor does not exist: {anchor}")
    assert_no_symlink_components(anchor, root)
    if not os.access(parent, os.W_OK):
        raise UnsafeOperationError(f"Studio root parent is not writable: {parent}")

    name = request.name.strip()
    engineer = request.engineer.strip()
    if not name:
        raise ValidationError("studio name must not be empty.")
    studio_id = require_slug(slugify(name), label="Studio ID")
    sample_rate = require_sample_rate(request.sample_rate)
    bit_depth = require_bit_depth(request.bit_depth)
    file_format = require_file_format(request.file_format)

    document: dict[str, Any] = {
        "metadata": create_v11("mixing-studio", mutability="mutable"),
        "studio_id": studio_id,
        "studio_name": name,
        "root_path": str(root),
        "defaults": {
            "mix_engineer": engineer,
            "audio": {
                "sample_rate": sample_rate,
                "bit_depth": bit_depth,
                "file_format": file_format,
            },
            "delivery": {
                "method": "Cloud transfer",
                "requested_deliverables": ["main_mix", "instrumental"],
            },
        },
        "cli": {"change_directory_after_create": request.default_cd},
    }
    validate_v11(document["metadata"], "mixing-studio", mutability="mutable")
    _validate_schema(document)
    config = root / "Studio" / "studio.json"

    if request.dry_run:
        return StudioCreateResult(root, config, document, False)

    stage = create_staging_directory(parent, f".{root.name}.jl-stage-")
    try:
        (stage / "Clients").mkdir()
        (stage / "Studio").mkdir()
        (stage / "Studio" / "studio.json").write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if root.exists() or root.is_symlink():
            raise UnsafeOperationError(f"Studio root already exists: {root}")
        commit_new_directory(stage, root)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise

    return StudioCreateResult(root, config, document, True)
