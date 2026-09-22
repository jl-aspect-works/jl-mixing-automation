"""Authoritative non-destructive revision close/reopen lifecycle service."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .context import resolve_project, revision_root_for_number
from .errors import ValidationError
from .metadata import now_iso8601, write_json_document
from .revision import _load_manifest, _validate_project_state, _validate_schema

LifecycleAction = Literal["close", "reopen"]


@dataclass(frozen=True)
class RevisionLifecycleRequest:
    project_root: Path
    revision: int
    action: LifecycleAction
    dry_run: bool = False


@dataclass(frozen=True)
class RevisionLifecycleResult:
    project_root: Path
    revision_root: Path
    number: int
    action: LifecycleAction
    lifecycle: str
    previous_current_revision: int
    current_revision: int
    approved_revision: int | None
    delivered_revision: int | None
    manifest: dict[str, Any]
    updated: bool


def revision_lifecycle(record: dict[str, Any]) -> str:
    """Return lifecycle for a revision, treating legacy records as open."""
    value = record.get("lifecycle", "open")
    if value not in {"open", "closed"}:
        raise ValidationError(f"Revision {record.get('number')} has invalid lifecycle state: {value}")
    return value


def effective_current_revision(document: dict[str, Any]) -> int:
    open_numbers = [
        record["number"]
        for record in document.get("revisions", [])
        if isinstance(record, dict)
        and isinstance(record.get("number"), int)
        and revision_lifecycle(record) == "open"
    ]
    return max(open_numbers, default=0)


def _find_revision(document: dict[str, Any], number: int) -> dict[str, Any]:
    matches = [
        record
        for record in document.get("revisions", [])
        if isinstance(record, dict) and record.get("number") == number
    ]
    if len(matches) != 1:
        raise ValidationError(f"Revision {number} does not exist.")
    return matches[0]


def set_revision_lifecycle(request: RevisionLifecycleRequest) -> RevisionLifecycleResult:
    if not isinstance(request.revision, int) or isinstance(request.revision, bool) or request.revision < 1:
        raise ValidationError(f"Revision number must be a positive integer: {request.revision}")
    if request.action not in {"close", "reopen"}:
        raise ValidationError(f"Unsupported revision lifecycle action: {request.action}")

    project_root = resolve_project(request.project_root, Path.cwd())
    manifest = _load_manifest(project_root)
    previous_current = _validate_project_state(manifest)
    record = _find_revision(manifest, request.revision)
    before = revision_lifecycle(record)
    desired = "closed" if request.action == "close" else "open"
    if before == desired:
        raise ValidationError(f"Revision {request.revision} is already {desired}.")

    updated = deepcopy(manifest)
    target = _find_revision(updated, request.revision)
    target["lifecycle"] = desired
    updated["state"]["current_revision"] = effective_current_revision(updated)
    updated["metadata"]["last_modified_at"] = now_iso8601()
    current = _validate_project_state(updated)
    _validate_schema(updated)

    revision_root = revision_root_for_number(project_root, request.revision)
    state = updated["state"]
    result = RevisionLifecycleResult(
        project_root=project_root,
        revision_root=revision_root,
        number=request.revision,
        action=request.action,
        lifecycle=desired,
        previous_current_revision=previous_current,
        current_revision=current,
        approved_revision=state.get("approved_revision"),
        delivered_revision=state.get("delivered_revision"),
        manifest=updated,
        updated=not request.dry_run,
    )
    if request.dry_run:
        return result

    write_json_document(project_root / "00_Admin" / "project-manifest.json", updated)
    return result
