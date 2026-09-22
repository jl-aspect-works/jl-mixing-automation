"""Authoritative cross-platform revision approval service."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .context import resolve_project, revision_root_for_number
from .errors import ValidationError
from .metadata import now_iso8601, write_json_document
from .revision import _load_manifest, _revision_lifecycle, _validate_project_state, _validate_schema


@dataclass(frozen=True)
class RevisionApproveRequest:
    project_root: Path
    revision: int | None = None
    approved_by: str = "Client"
    approved_at: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class RevisionApproveResult:
    project_root: Path
    revision_root: Path
    number: int
    approved_by: str
    approved_at: str | None
    previous_approved_revision: int | None
    current_revision: int
    delivered_revision: int | None
    manifest: dict[str, Any]
    updated: bool


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"Invalid {label}: {value}") from exc
    if parsed.utcoffset() is None:
        raise ValidationError(f"Invalid {label}: timestamp must include a UTC offset or Z")
    return parsed


def _find_revision(document: dict[str, Any], number: int) -> dict[str, Any]:
    matches = [record for record in document.get("revisions", []) if isinstance(record, dict) and record.get("number") == number]
    if len(matches) != 1:
        raise ValidationError(f"Revision {number} does not exist.")
    return matches[0]


def derive_project_stage(document: dict[str, Any]) -> str:
    state = document["state"]
    current = state["current_revision"]
    approved = state.get("approved_revision")
    delivered = state.get("delivered_revision")
    if current == 0:
        if delivered is not None:
            return "Delivered"
        if approved is not None:
            return "Approved"
        return "Setup"
    if current != approved:
        return "In progress"
    if delivered != current:
        return "Approved"
    return "Delivered"


def approve_revision(request: RevisionApproveRequest) -> RevisionApproveResult:
    project_root = resolve_project(request.project_root, Path.cwd())
    manifest = _load_manifest(project_root)
    current = _validate_project_state(manifest)
    if current == 0 and request.revision is None:
        raise ValidationError("No open revision exists to approve.")

    number = current if request.revision is None else request.revision
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ValidationError(f"Revision number must be a positive integer: {number}")
    revision = _find_revision(manifest, number)
    if _revision_lifecycle(revision) != "open":
        raise ValidationError(f"Revision {number} is closed and cannot be approved until it is reopened.")
    revision_root = revision_root_for_number(project_root, number)

    approved_by = request.approved_by.strip()
    if not approved_by:
        raise ValidationError("approver must not be empty.")

    state = manifest["state"]
    previous_approved = state.get("approved_revision")
    delivered = state.get("delivered_revision")
    if previous_approved == number:
        raise ValidationError(f"Revision {number} is already the approved revision.")

    created_at = revision.get("created_at")
    if not isinstance(created_at, str):
        raise ValidationError(f"Revision {number} has an invalid creation timestamp.")
    created = _parse_timestamp(created_at, "revision creation timestamp")

    approved_at = request.approved_at.strip() if request.approved_at is not None else None
    if approved_at == "":
        raise ValidationError("approval timestamp must not be empty.")
    if approved_at is not None:
        approved = _parse_timestamp(approved_at, "approval timestamp")
        if approved < created:
            raise ValidationError(f"Invalid approval timestamp: {approved_at}; timestamp predates revision creation")

    updated = deepcopy(manifest)
    effective_timestamp = approved_at or now_iso8601()
    approved = _parse_timestamp(effective_timestamp, "approval timestamp")
    if approved < created:
        raise ValidationError(f"Invalid approval timestamp: {effective_timestamp}; timestamp predates revision creation")

    target = _find_revision(updated, number)
    target["approval"] = {"approved_at": effective_timestamp, "approved_by": approved_by}
    updated["state"]["approved_revision"] = number
    updated["metadata"]["last_modified_at"] = effective_timestamp
    _validate_project_state(updated)
    _validate_schema(updated)

    if request.dry_run:
        return RevisionApproveResult(
            project_root, revision_root, number, approved_by, approved_at,
            previous_approved, current, delivered, updated, False,
        )

    write_json_document(project_root / "00_Admin" / "project-manifest.json", updated)
    return RevisionApproveResult(
        project_root, revision_root, number, approved_by, effective_timestamp,
        previous_approved, current, delivered, updated, True,
    )
