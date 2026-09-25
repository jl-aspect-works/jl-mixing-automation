"""Automation API 1.0 contract for permanent Original Delivery deletion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import resolve_project
from ..errors import ArgumentError, ContextError, UnsafeOperationError, ValidationError
from ..managed_client_file_delete import PartialCleanupError, execute as execute_delete, plan as plan_delete
from ..versions import api_version


@dataclass(frozen=True)
class DeleteRequest:
    project: Path
    relative_path: str
    fingerprint: str | None = None
    confirmed_name: str | None = None


def _envelope(operation: str, status: str, data: dict[str, Any], errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"api_version": api_version(), "operation": operation, "status": status,
            "data": data, "warnings": [], "errors": errors or []}


def _error(operation: str, code: str, message: str, exit_code: int, *, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _envelope(operation, "error" if exit_code == 1 else "blocked", data or {},
                     [{"code": code, "message": message, "details": {"exit_code": exit_code}, "retryable": False}])


def run(request: DeleteRequest, *, plan_only: bool) -> tuple[dict[str, Any], int]:
    operation = "client.files.delete.plan" if plan_only else "client.files.delete.execute"
    try:
        root = resolve_project(request.project, Path.cwd())
        summary = plan_delete(root, request.relative_path) if plan_only else execute_delete(
            root, request.relative_path, request.fingerprint or "", request.confirmed_name or "")
        return _envelope(operation, "planned" if plan_only else "success", {
            "summary": summary, "deleted": not plan_only, "recoverable": False,
        }), 0
    except (ContextError, ValidationError, UnsafeOperationError) as exc:
        code = "NOT_FOUND" if isinstance(exc, ContextError) else "UNSAFE_OPERATION" if isinstance(exc, UnsafeOperationError) else "VALIDATION_FAILED"
        return _error(operation, code, str(exc), exc.exit_code), exc.exit_code
    except PartialCleanupError as exc:
        return _error(operation, "PARTIAL_CLEANUP", str(exc), 1,
                      data={"deleted": False, "partial_cleanup": True, "remaining_path": str(exc.path)}), 1
    except OSError as exc:
        return _error(operation, "FILESYSTEM_ERROR", str(exc), 1), 1


def parse_args(args: list[str], *, plan_only: bool) -> DeleteRequest:
    options = {"--project": "project", "--relative-path": "relative_path",
               "--fingerprint": "fingerprint", "--confirm-name": "confirmed_name"}
    values: dict[str, Any] = {}
    json_seen = 0
    index = 0
    while index < len(args):
        flag = args[index]
        if flag == "--json":
            json_seen += 1
        elif flag in options:
            index += 1
            if index >= len(args) or options[flag] in values:
                raise ArgumentError(f"{flag} requires exactly one value.")
            values[options[flag]] = Path(args[index]) if flag == "--project" else args[index]
        else:
            raise ArgumentError(f"Unknown Client Files deletion option: {flag}")
        index += 1
    if json_seen != 1 or not all(values.get(key) for key in ("project", "relative_path")):
        raise ArgumentError("Client Files deletion requires --json, --project, and --relative-path.")
    if plan_only and ("fingerprint" in values or "confirmed_name" in values):
        raise ArgumentError("Deletion planning does not accept execution confirmation.")
    if not plan_only and not all(values.get(key) for key in ("fingerprint", "confirmed_name")):
        raise ArgumentError("Deletion execution requires --fingerprint and --confirm-name.")
    return DeleteRequest(**values)
