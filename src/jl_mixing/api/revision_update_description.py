"""Automation API 1.0 adapter for revision.update-description."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import resolve_project, studio_root
from ..errors import ArgumentError, ContextError, JLMixingError, ValidationError
from ..revision_description import (
    RevisionDescriptionUpdateRequest,
    update_revision_description,
)
from ..versions import api_version


@dataclass(frozen=True)
class RevisionDescriptionApiRequest:
    project: Path | None = None
    revision: int | None = None
    description: str | None = None
    dry_run: bool = False


def _error_envelope(
    code: str,
    message: str,
    exit_code: int,
    *,
    status: str = "error",
) -> dict[str, Any]:
    return {
        "api_version": api_version(),
        "operation": "revision.update-description",
        "status": status,
        "data": {},
        "warnings": [],
        "errors": [
            {
                "code": code,
                "message": message,
                "details": {"exit_code": exit_code},
                "retryable": False,
            }
        ],
    }


def execute(request: RevisionDescriptionApiRequest) -> tuple[dict[str, Any], int]:
    try:
        project_root = resolve_project(request.project, Path.cwd())
        if request.revision is None:
            raise ValidationError("revision number is required.")
        if request.description is None:
            raise ValidationError("revision description is required.")
        result = update_revision_description(
            RevisionDescriptionUpdateRequest(
                project_root=project_root,
                revision=request.revision,
                description=request.description,
                dry_run=request.dry_run,
            )
        )
        manifest_path = result.project_root / "00_Admin" / "project-manifest.json"
        data: dict[str, Any] = {
            "project": {
                "id": result.manifest.get("project_id", ""),
                "path": str(result.project_root),
            },
            "manifest_path": str(manifest_path),
            "revision": {
                "number": result.revision,
                "revision_id": result.revision_id,
                "description": result.description,
                "previous_description": result.previous_description,
            },
            "workspace_path": str(studio_root(result.project_root)),
            "changed": result.description != result.previous_description,
        }
        if request.dry_run:
            data["would_update"] = [str(manifest_path)]
        return {
            "api_version": api_version(),
            "operation": "revision.update-description",
            "status": "planned" if request.dry_run else "success",
            "data": data,
            "warnings": [],
            "errors": [],
        }, 0
    except ContextError as exc:
        return _error_envelope(
            "WORKSPACE_CONTEXT_ERROR", str(exc), exc.exit_code
        ), exc.exit_code
    except ValidationError as exc:
        message = str(exc)
        code = (
            "REVISION_NOT_FOUND"
            if "does not exist" in message.lower()
            else "VALIDATION_FAILED"
        )
        return _error_envelope(
            code, message, exc.exit_code, status="blocked"
        ), exc.exit_code
    except JLMixingError as exc:
        return _error_envelope(
            "INTERNAL_ERROR", str(exc), exc.exit_code
        ), exc.exit_code


def parse_args(args: list[str]) -> RevisionDescriptionApiRequest:
    project: Path | None = None
    revision: int | None = None
    description: str | None = None
    dry_run = False
    json_seen = 0
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json":
            json_seen += 1
        elif arg in {"--project", "--revision", "--description"}:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--project":
                project = Path(value)
            elif arg == "--revision":
                try:
                    revision = int(value)
                except ValueError as exc:
                    raise ArgumentError("--revision requires an integer.") from exc
            else:
                description = value
        elif arg == "--dry-run":
            dry_run = True
        elif arg.startswith("-"):
            raise ArgumentError(f"Unknown option: {arg}")
        else:
            raise ArgumentError(f"Unexpected positional argument: {arg}")
        index += 1
    if json_seen != 1:
        raise ArgumentError(
            "revision update-description requires exactly one --json option."
        )
    if revision is None:
        raise ArgumentError("revision update-description requires --revision.")
    if description is None:
        raise ArgumentError("revision update-description requires --description.")
    return RevisionDescriptionApiRequest(
        project=project,
        revision=revision,
        description=description,
        dry_run=dry_run,
    )
