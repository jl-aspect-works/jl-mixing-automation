"""Automation API 1.0 adapter for revision.unapprove."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import studio_root
from ..errors import ArgumentError, ContextError, JLMixingError, ValidationError
from ..unapproval import RevisionUnapproveRequest, unapprove_revision
from ..versions import api_version


@dataclass(frozen=True)
class RevisionUnapproveApiRequest:
    project: Path
    revision: int
    dry_run: bool = False


def _error(code: str, message: str, exit_code: int, *, status: str = "error") -> dict[str, Any]:
    return {
        "api_version": api_version(), "operation": "revision.unapprove", "status": status, "data": {}, "warnings": [],
        "errors": [{"code": code, "message": message, "details": {"exit_code": exit_code}, "retryable": False}],
    }


def execute(request: RevisionUnapproveApiRequest) -> tuple[dict[str, Any], int]:
    try:
        result = unapprove_revision(RevisionUnapproveRequest(
            project_root=request.project, revision=request.revision, dry_run=request.dry_run,
        ))
        manifest_path = result.project_root / "00_Admin" / "project-manifest.json"
        data: dict[str, Any] = {
            "project": {"id": result.manifest.get("project_id", ""), "path": str(result.project_root)},
            "workspace_path": str(studio_root(result.project_root)),
            "manifest_path": str(manifest_path),
            "revision": {"number": result.number, "path": str(result.revision_root)},
            "state": {
                "current_revision": result.current_revision,
                "approved_revision": None,
                "delivered_revision": result.delivered_revision,
            },
        }
        if request.dry_run:
            data["would_update"] = [str(manifest_path)]
        return {
            "api_version": api_version(), "operation": "revision.unapprove",
            "status": "planned" if request.dry_run else "success", "data": data, "warnings": [], "errors": [],
        }, 0
    except ContextError as exc:
        return _error("PROJECT_NOT_FOUND", str(exc), exc.exit_code), exc.exit_code
    except ValidationError as exc:
        message = str(exc)
        lowered = message.lower()
        if "does not exist" in lowered:
            code = "REVISION_NOT_FOUND"
        elif "is not the approved revision" in lowered:
            code = "REVISION_NOT_APPROVED"
        elif "delivered revision" in lowered:
            code = "REVISION_DELIVERED"
        else:
            code = "VALIDATION_FAILED"
        return _error(code, message, exc.exit_code, status="blocked"), exc.exit_code
    except JLMixingError as exc:
        return _error("INTERNAL_ERROR", str(exc), exc.exit_code), exc.exit_code


def parse_args(args: list[str]) -> RevisionUnapproveApiRequest:
    project: Path | None = None
    revision: int | None = None
    dry_run = False
    json_seen = 0
    project_seen = 0
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json":
            json_seen += 1
        elif arg in {"--project", "--revision"}:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--project":
                project_seen += 1
                project = Path(value)
            else:
                try:
                    revision = int(value)
                except ValueError as exc:
                    raise ValidationError(f"Revision number must be a positive integer: {value}") from exc
        elif arg == "--dry-run":
            dry_run = True
        elif arg.startswith("-"):
            raise ArgumentError(f"Unknown option: {arg}")
        else:
            raise ArgumentError(f"Unexpected positional argument: {arg}")
        index += 1
    if json_seen != 1:
        raise ArgumentError("revision unapprove requires exactly one --json option.")
    if project_seen != 1 or project is None:
        raise ArgumentError("revision unapprove JSON mode requires exactly one --project PATH option.")
    if revision is None:
        raise ArgumentError("revision unapprove requires --revision NUMBER.")
    return RevisionUnapproveApiRequest(project=project, revision=revision, dry_run=dry_run)
