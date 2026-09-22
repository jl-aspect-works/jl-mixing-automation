"""Authoritative revision unapproval service."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .context import resolve_project, revision_root_for_number
from .errors import ValidationError
from .metadata import now_iso8601, write_json_document
from .revision import _load_manifest, _validate_project_state, _validate_schema


@dataclass(frozen=True)
class RevisionUnapproveRequest:
    project_root: Path
    revision: int
    dry_run: bool = False


@dataclass(frozen=True)
class RevisionUnapproveResult:
    project_root: Path
    revision_root: Path
    number: int
    current_revision: int
    delivered_revision: int | None
    manifest: dict[str, Any]
    updated: bool


def _find_revision(document: dict[str, Any], number: int) -> dict[str, Any]:
    matches = [record for record in document.get("revisions", []) if isinstance(record, dict) and record.get("number") == number]
    if len(matches) != 1:
        raise ValidationError(f"Revision {number} does not exist.")
    return matches[0]


def unapprove_revision(request: RevisionUnapproveRequest) -> RevisionUnapproveResult:
    if not isinstance(request.revision, int) or isinstance(request.revision, bool) or request.revision < 1:
        raise ValidationError(f"Revision number must be a positive integer: {request.revision}")
    project_root = resolve_project(request.project_root, Path.cwd())
    manifest = _load_manifest(project_root)
    current = _validate_project_state(manifest)
    _find_revision(manifest, request.revision)
    state = manifest["state"]
    if state.get("approved_revision") != request.revision:
        raise ValidationError(f"Revision {request.revision} is not the approved revision.")
    delivered = state.get("delivered_revision")
    if delivered == request.revision:
        raise ValidationError(
            f"Revision {request.revision} cannot be unapproved because it is the delivered revision. Resolve delivery state first."
        )

    updated = deepcopy(manifest)
    target = _find_revision(updated, request.revision)
    target["approval"] = {"approved_at": None, "approved_by": None}
    updated["state"]["approved_revision"] = None
    updated["metadata"]["last_modified_at"] = now_iso8601()
    _validate_project_state(updated)
    _validate_schema(updated)

    result = RevisionUnapproveResult(
        project_root=project_root,
        revision_root=revision_root_for_number(project_root, request.revision),
        number=request.revision,
        current_revision=current,
        delivered_revision=delivered,
        manifest=updated,
        updated=not request.dry_run,
    )
    if request.dry_run:
        return result
    write_json_document(project_root / "00_Admin" / "project-manifest.json", updated)
    return result
