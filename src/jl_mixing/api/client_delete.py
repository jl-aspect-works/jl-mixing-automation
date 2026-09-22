"""Machine-facing plan/execute contract for permanent empty-client deletion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..client_delete import (
    ClientNotEmptyError,
    PartialDeletionError,
    execute_client_delete,
    plan_client_delete,
)
from ..errors import ArgumentError, ContextError, UnsafeOperationError, ValidationError
from ..versions import api_version


@dataclass(frozen=True)
class ClientDeleteRequest:
    workspace: Path
    client_id: str
    fingerprint: str | None = None
    confirmed_name: str | None = None


def _envelope(operation: str, status: str, data: dict[str, Any], errors: list[dict[str, Any]]) -> dict[str, Any]:
    return {"api_version": api_version(), "operation": operation, "status": status,
            "data": data, "warnings": [], "errors": errors}


def _error(operation: str, code: str, message: str, exit_code: int, *,
           status: str = "blocked", data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _envelope(operation, status, data or {}, [{"code": code, "message": message,
        "details": {"exit_code": exit_code}, "retryable": False}])


def execute(request: ClientDeleteRequest, *, plan_only: bool) -> tuple[dict[str, Any], int]:
    operation = "client.delete.plan" if plan_only else "client.delete.execute"
    try:
        if plan_only:
            plan = plan_client_delete(request.workspace, request.client_id)
        else:
            plan = execute_client_delete(request.workspace, request.client_id,
                fingerprint=request.fingerprint or "", confirmed_name=request.confirmed_name or "")
        data = {"summary": plan.summary(), "deleted": not plan_only, "recoverable": False}
        return _envelope(operation, "planned" if plan_only else "success", data, []), 0
    except ClientNotEmptyError as exc:
        return _error(operation, "CLIENT_NOT_EMPTY", str(exc), exc.exit_code,
                      data={"deleted": False, "project_count": exc.project_count, "recoverable": False}), exc.exit_code
    except (ContextError, ValidationError, UnsafeOperationError) as exc:
        code = "NOT_FOUND" if isinstance(exc, ContextError) else "UNSAFE_OPERATION" if isinstance(exc, UnsafeOperationError) else "VALIDATION_FAILED"
        return _error(operation, code, str(exc), exc.exit_code), exc.exit_code
    except PartialDeletionError as exc:
        return _error(operation, "PARTIAL_CLEANUP", str(exc), 1, status="error", data={
            "deleted": False, "partial_cleanup": True, "remaining_path": str(exc.path),
            "recoverable": False}), 1
    except OSError as exc:
        return _error(operation, "FILESYSTEM_ERROR", str(exc), 1, status="error"), 1


def parse_args(args: list[str], *, plan_only: bool) -> ClientDeleteRequest:
    options = {"--workspace": "workspace", "--client-id": "client_id",
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
            values[options[flag]] = Path(args[index]) if flag == "--workspace" else args[index]
        else:
            raise ArgumentError(f"Unknown client deletion option: {flag}")
        index += 1
    if json_seen != 1 or not all(values.get(key) for key in ("workspace", "client_id")):
        raise ArgumentError("Client deletion requires --json, --workspace, and --client-id.")
    if plan_only and ("fingerprint" in values or "confirmed_name" in values):
        raise ArgumentError("Client deletion planning does not accept execution confirmation.")
    if not plan_only and not all(values.get(key) for key in ("fingerprint", "confirmed_name")):
        raise ArgumentError("Client deletion execution requires --fingerprint and --confirm-name.")
    return ClientDeleteRequest(**values)
