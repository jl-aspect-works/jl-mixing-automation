"""Automation API 1.0 adapter for revision.create."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import resolve_project, studio_root
from ..errors import ArgumentError, ContextError, JLMixingError, UnsafeOperationError, ValidationError
from ..revision import RevisionCreateRequest, create_revision
from ..versions import api_version


@dataclass(frozen=True)
class RevisionApiRequest:
    project: Path | None = None
    description: str | None = None
    source: Path | None = None
    dry_run: bool = False


def _error_envelope(code: str, message: str, exit_code: int, *, status: str = "error") -> dict[str, Any]:
    return {
        "api_version": api_version(),
        "operation": "revision.create",
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


def execute(request: RevisionApiRequest) -> tuple[dict[str, Any], int]:
    try:
        project_root = resolve_project(request.project, Path.cwd())
        result = create_revision(RevisionCreateRequest(
            project_root=project_root,
            description=request.description,
            source=request.source,
            change_directory=False,
            dry_run=request.dry_run,
        ))
        manifest_path = result.project_root / "00_Admin" / "project-manifest.json"
        workspace = studio_root(result.project_root)
        project_id = result.manifest.get("project_id", "")
        data: dict[str, Any] = {
            "project": {"id": project_id, "path": str(result.project_root)},
            "manifest_path": str(manifest_path),
            "revision": {
                "number": result.number,
                "path": str(result.revision_root),
                "description": result.description,
            },
            "revision_notes_path": str(result.revision_root / "Revision_Notes.md"),
            "workspace_path": str(workspace),
        }
        if request.dry_run:
            data["would_create"] = [
                str(result.revision_root),
                str(result.revision_root / "Revision_Notes.md"),
            ]
            data["would_update"] = [str(manifest_path)]
        return {
            "api_version": api_version(),
            "operation": "revision.create",
            "status": "planned" if request.dry_run else "success",
            "data": data,
            "warnings": [],
            "errors": [],
        }, 0
    except ContextError as exc:
        message = str(exc)
        code = "SOURCE_NOT_FOUND" if "revision source not found" in message.lower() else "WORKSPACE_CONTEXT_ERROR"
        return _error_envelope(code, message, exc.exit_code), exc.exit_code
    except ValidationError as exc:
        message = str(exc)
        code = "REVISION_ALREADY_EXISTS" if "collision" in message.lower() or "already exists" in message.lower() else "VALIDATION_FAILED"
        return _error_envelope(code, message, exc.exit_code, status="blocked"), exc.exit_code
    except UnsafeOperationError as exc:
        message = str(exc)
        code = "REVISION_ALREADY_EXISTS" if "already exists" in message.lower() else "UNSAFE_OPERATION"
        return _error_envelope(code, message, exc.exit_code, status="blocked"), exc.exit_code
    except JLMixingError as exc:
        return _error_envelope("INTERNAL_ERROR", str(exc), exc.exit_code), exc.exit_code


def parse_args(args: list[str]) -> RevisionApiRequest:
    project: Path | None = None
    description: str | None = None
    source: Path | None = None
    dry_run = False
    json_seen = 0
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json":
            json_seen += 1
        elif arg in {"--cd", "--no-cd"}:
            raise ArgumentError("revision create JSON mode does not accept --cd or --no-cd.")
        elif arg in {"--project", "--description", "--source"}:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--project":
                project = Path(value)
            elif arg == "--description":
                description = value
            else:
                source = Path(value)
        elif arg == "--dry-run":
            dry_run = True
        elif arg.startswith("-"):
            raise ArgumentError(f"Unknown option: {arg}")
        else:
            raise ArgumentError(f"Unexpected positional argument: {arg}")
        index += 1
    if json_seen != 1:
        raise ArgumentError("revision create requires exactly one --json option.")
    return RevisionApiRequest(project=project, description=description, source=source, dry_run=dry_run)
