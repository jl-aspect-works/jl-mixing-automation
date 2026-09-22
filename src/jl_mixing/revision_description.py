"""Authoritative revision description update service."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .context import resolve_project, studio_root as resolve_studio_root
from .errors import ValidationError
from .metadata import now_iso8601
from .paths import assert_no_symlink_components
from .revision import _load_manifest, _validate_project_state, _validate_schema
from .transactions import create_staging_file


@dataclass(frozen=True)
class RevisionDescriptionUpdateRequest:
    project_root: Path
    revision: int
    description: str
    dry_run: bool = False


@dataclass(frozen=True)
class RevisionDescriptionUpdateResult:
    project_root: Path
    revision: int
    revision_id: str
    previous_description: str
    description: str
    manifest: dict[str, Any]
    updated: bool


def update_revision_description(
    request: RevisionDescriptionUpdateRequest,
) -> RevisionDescriptionUpdateResult:
    project_root = resolve_project(request.project_root, Path.cwd())
    studio_root = resolve_studio_root(project_root)
    assert_no_symlink_components(studio_root, project_root)

    if isinstance(request.revision, bool) or request.revision < 1:
        raise ValidationError("revision number must be a positive integer.")
    description = request.description.strip()
    if not description:
        raise ValidationError("revision description must not be empty.")

    manifest_path = project_root / "00_Admin" / "project-manifest.json"
    manifest = _load_manifest(project_root)
    _validate_project_state(manifest)

    record = next(
        (
            item
            for item in manifest.get("revisions", [])
            if isinstance(item, dict) and item.get("number") == request.revision
        ),
        None,
    )
    if record is None:
        raise ValidationError(f"Revision {request.revision} does not exist.")

    previous_description = record.get("description")
    if not isinstance(previous_description, str):
        raise ValidationError(f"Revision {request.revision} has an invalid description.")
    revision_id = record.get("revision_id")
    if not isinstance(revision_id, str) or not revision_id:
        raise ValidationError(f"Revision {request.revision} has an invalid revision ID.")

    updated = deepcopy(manifest)
    updated_record = next(
        item for item in updated["revisions"] if item.get("number") == request.revision
    )
    updated_record["description"] = description
    updated["metadata"]["last_modified_at"] = now_iso8601()
    _validate_project_state(updated)
    _validate_schema(updated)

    if request.dry_run or description == previous_description:
        return RevisionDescriptionUpdateResult(
            project_root=project_root,
            revision=request.revision,
            revision_id=revision_id,
            previous_description=previous_description,
            description=description,
            manifest=updated,
            updated=False,
        )

    fd, temp_path = create_staging_file(manifest_path.parent, f".{manifest_path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(updated, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, manifest_path.stat().st_mode & 0o777)
        os.replace(temp_path, manifest_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return RevisionDescriptionUpdateResult(
        project_root=project_root,
        revision=request.revision,
        revision_id=revision_id,
        previous_description=previous_description,
        description=description,
        manifest=updated,
        updated=True,
    )
