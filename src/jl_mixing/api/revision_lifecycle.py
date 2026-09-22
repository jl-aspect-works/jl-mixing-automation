"""Automation API 1.0 adapter for revision.close and revision.reopen."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import studio_root
from ..errors import ArgumentError, ContextError, JLMixingError, ValidationError
from ..revision_lifecycle import RevisionLifecycleRequest, set_revision_lifecycle
from ..versions import api_version


@dataclass(frozen=True)
class RevisionLifecycleApiRequest:
    project: Path
    revision: int
    action: str
    dry_run: bool = False


def _error(operation: str, code: str, message: str, exit_code: int, *, status: str = "error") -> dict[str, Any]:
    return {
        "api_version": api_version(), "operation": operation, "status": status, "data": {}, "warnings": [],
        "errors": [{"code": code, "message": message, "details": {"exit_code": exit_code}, "retryable": False}],
    }


def execute(request: RevisionLifecycleApiRequest) -> tuple[dict[str, Any], int]:
    operation = f"revision.{request.action}"
    try:
        result = set_revision_lifecycle(RevisionLifecycleRequest(
            project_root=request.project, revision=request.revision, action=request.action, dry_run=request.dry_run,
        ))
        manifest_path = result.project_root / "00_Admin" / "project-manifest.json"
        data: dict[str, Any] = {
            "project": {"id": result.manifest.get("project_id", ""), "path": str(result.project_root)},
            "workspace_path": str(studio_root(result.project_root)),
            "manifest_path": str(manifest_path),
            "revision": {"number": result.number, "path": str(result.revision_root), "lifecycle": result.lifecycle},
            "state": {
                "current_revision": result.current_revision,
                "approved_revision": result.approved_revision,
                "delivered_revision": result.delivered_revision,
            },
        }
        if request.dry_run:
            data["would_update"] = [str(manifest_path)]
        return {
            "api_version": api_version(), "operation": operation,
            "status": "planned" if request.dry_run else "success", "data": data, "warnings": [], "errors": [],
        }, 0
    except ContextError as exc:
        return _error(operation, "PROJECT_NOT_FOUND", str(exc), exc.exit_code), exc.exit_code
    except ValidationError as exc:
        message = str(exc)
        lowered = message.lower()
        if "does not exist" in lowered:
            code = "REVISION_NOT_FOUND"
        elif "already open" in lowered:
            code = "REVISION_ALREADY_OPEN"
        elif "already closed" in lowered:
            code = "REVISION_ALREADY_CLOSED"
        else:
            code = "VALIDATION_FAILED"
        return _error(operation, code, message, exc.exit_code, status="blocked"), exc.exit_code
    except JLMixingError as exc:
        return _error(operation, "INTERNAL_ERROR", str(exc), exc.exit_code), exc.exit_code


def parse_args(args: list[str], action: str) -> RevisionLifecycleApiRequest:
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
        raise ArgumentError(f"revision {action} requires exactly one --json option.")
    if project_seen != 1 or project is None:
        raise ArgumentError(f"revision {action} JSON mode requires exactly one --project PATH option.")
    if revision is None:
        raise ArgumentError(f"revision {action} requires --revision NUMBER.")
    return RevisionLifecycleApiRequest(project=project, revision=revision, action=action, dry_run=dry_run)
