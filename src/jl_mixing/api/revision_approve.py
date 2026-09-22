"""Automation API 1.0 adapter for revision.approve."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..approval import RevisionApproveRequest, approve_revision
from ..context import studio_root
from ..errors import ArgumentError, ContextError, JLMixingError, ValidationError
from ..versions import api_version


@dataclass(frozen=True)
class RevisionApproveApiRequest:
    project: Path
    revision: int | None = None
    approved_by: str = "Client"
    approved_at: str | None = None
    dry_run: bool = False


def _error_envelope(code: str, message: str, exit_code: int, *, status: str = "error") -> dict[str, Any]:
    return {
        "api_version": api_version(),
        "operation": "revision.approve",
        "status": status,
        "data": {},
        "warnings": [],
        "errors": [{
            "code": code,
            "message": message,
            "details": {"exit_code": exit_code},
            "retryable": False,
        }],
    }


def execute(request: RevisionApproveApiRequest) -> tuple[dict[str, Any], int]:
    try:
        result = approve_revision(RevisionApproveRequest(
            project_root=request.project,
            revision=request.revision,
            approved_by=request.approved_by,
            approved_at=request.approved_at,
            dry_run=request.dry_run,
        ))
        manifest_path = result.project_root / "00_Admin" / "project-manifest.json"
        workspace = studio_root(result.project_root)
        data: dict[str, Any] = {
            "project": {
                "id": result.manifest.get("project_id", ""),
                "path": str(result.project_root),
            },
            "manifest_path": str(manifest_path),
            "workspace_path": str(workspace),
            "revision": {
                "number": result.number,
                "path": str(result.revision_root),
            },
            "approved_by": result.approved_by,
            "approved_at": None if request.dry_run else result.approved_at,
        }
        if request.dry_run:
            data["would_update"] = [str(manifest_path)]
        return {
            "api_version": api_version(),
            "operation": "revision.approve",
            "status": "planned" if request.dry_run else "success",
            "data": data,
            "warnings": [],
            "errors": [],
        }, 0
    except ContextError as exc:
        return _error_envelope("PROJECT_NOT_FOUND", str(exc), exc.exit_code), exc.exit_code
    except ValidationError as exc:
        message = str(exc)
        lowered = message.lower()
        if "already the approved revision" in lowered:
            code = "REVISION_ALREADY_APPROVED"
        elif "does not exist" in lowered or "no revision exists" in lowered:
            code = "REVISION_NOT_FOUND"
        elif "approval timestamp" in lowered or "timestamp predates" in lowered or "utc offset" in lowered:
            code = "INVALID_APPROVAL_TIMESTAMP"
        else:
            code = "VALIDATION_FAILED"
        return _error_envelope(code, message, exc.exit_code, status="blocked"), exc.exit_code
    except JLMixingError as exc:
        return _error_envelope("INTERNAL_ERROR", str(exc), exc.exit_code), exc.exit_code


def parse_args(args: list[str]) -> RevisionApproveApiRequest:
    project: Path | None = None
    revision: int | None = None
    approved_by = "Client"
    approved_at: str | None = None
    dry_run = False
    json_seen = 0
    project_seen = 0
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json":
            json_seen += 1
        elif arg in {"--project", "--revision", "--approved-by", "--date"}:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--project":
                project_seen += 1
                project = Path(value)
            elif arg == "--revision":
                try:
                    revision = int(value)
                except ValueError as exc:
                    raise ValidationError(f"Revision number must be a positive integer: {value}") from exc
            elif arg == "--approved-by":
                approved_by = value
            else:
                approved_at = value
        elif arg == "--dry-run":
            dry_run = True
        elif arg in {"--notes", "--non-interactive"}:
            raise ArgumentError(f"Unknown option: {arg}")
        elif arg.startswith("-"):
            raise ArgumentError(f"Unknown option: {arg}")
        else:
            raise ArgumentError(f"Unexpected positional argument: {arg}")
        index += 1

    if json_seen != 1:
        raise ArgumentError("revision approve requires exactly one --json option.")
    if project_seen != 1 or project is None or str(project) == "":
        raise ArgumentError("revision approve JSON mode requires exactly one --project PATH option.")
    return RevisionApproveApiRequest(
        project=project,
        revision=revision,
        approved_by=approved_by,
        approved_at=approved_at,
        dry_run=dry_run,
    )
