"""Automation API 1.0 adapter for client.update."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..client_update import ClientUpdateRequest, update_client
from ..context import resolve_client_reference, studio_root
from ..errors import ArgumentError, ContextError, JLMixingError, UnsafeOperationError, ValidationError
from ..versions import api_version


@dataclass(frozen=True)
class ClientUpdateApiRequest:
    client: str | Path | None = None
    client_name: str | None = None
    artist: str | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    file_format: str | None = None
    delivery_method: str | None = None
    requested_deliverables: tuple[str, ...] | None = None
    dry_run: bool = False


def _error_envelope(code: str, message: str, exit_code: int, *, status: str = "error") -> dict[str, Any]:
    return {
        "api_version": api_version(),
        "operation": "client.update",
        "status": status,
        "data": {},
        "warnings": [],
        "errors": [{"code": code, "message": message, "details": {"exit_code": exit_code}, "retryable": False}],
    }


def execute(request: ClientUpdateApiRequest) -> tuple[dict[str, Any], int]:
    try:
        root = resolve_client_reference(request.client, Path.cwd())
        result = update_client(ClientUpdateRequest(
            client_root=root,
            client_name=request.client_name,
            artist=request.artist,
            sample_rate=request.sample_rate,
            bit_depth=request.bit_depth,
            file_format=request.file_format,
            delivery_method=request.delivery_method,
            requested_deliverables=request.requested_deliverables,
            dry_run=request.dry_run,
        ))
        doc = result.document
        data: dict[str, Any] = {
            "client": {"id": doc["client_id"], "path": str(result.client_root), "configuration_path": str(result.client_config)},
            "workspace_path": str(studio_root(result.client_root)),
            "changed_fields": list(result.changed_fields),
            "editable": {
                "client_name": doc["client_name"],
                "artist": doc["defaults"]["artist"],
                "audio": doc["defaults"]["audio"],
                "delivery": doc["defaults"]["delivery"],
            },
            "last_modified_at": doc["metadata"]["last_modified_at"],
            "changed": bool(result.changed_fields),
        }
        if request.dry_run:
            data["would_update"] = [str(result.client_config)] if result.changed_fields else []
        return {
            "api_version": api_version(), "operation": "client.update",
            "status": "planned" if request.dry_run else "success",
            "data": data, "warnings": [], "errors": [],
        }, 0
    except ContextError as exc:
        return _error_envelope("WORKSPACE_CONTEXT_ERROR", str(exc), exc.exit_code), exc.exit_code
    except UnsafeOperationError as exc:
        return _error_envelope("UNSAFE_OPERATION", str(exc), exc.exit_code, status="blocked"), exc.exit_code
    except ValidationError as exc:
        return _error_envelope("VALIDATION_FAILED", str(exc), exc.exit_code, status="blocked"), exc.exit_code
    except JLMixingError as exc:
        return _error_envelope("INTERNAL_ERROR", str(exc), exc.exit_code), exc.exit_code
    except OSError as exc:
        return _error_envelope("FILESYSTEM_ERROR", str(exc), 1), 1


def parse_args(args: list[str]) -> ClientUpdateApiRequest:
    values: dict[str, Any] = {"dry_run": False}
    json_seen = 0
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json": json_seen += 1
        elif arg == "--dry-run": values["dry_run"] = True
        elif arg in {"--client", "--name", "--artist", "--sample-rate", "--bit-depth", "--file-format", "--delivery-method", "--deliverables"}:
            index += 1
            if index >= len(args): raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--client": values["client"] = value
            elif arg == "--name": values["client_name"] = value
            elif arg == "--artist": values["artist"] = value
            elif arg == "--sample-rate":
                try: values["sample_rate"] = int(value)
                except ValueError as exc: raise ArgumentError("--sample-rate requires an integer.") from exc
            elif arg == "--bit-depth":
                try: values["bit_depth"] = int(value)
                except ValueError as exc: raise ArgumentError("--bit-depth requires an integer.") from exc
            elif arg == "--file-format": values["file_format"] = value
            elif arg == "--delivery-method": values["delivery_method"] = value
            else: values["requested_deliverables"] = tuple(part.strip() for part in value.split(","))
        elif arg.startswith("-"): raise ArgumentError(f"Unknown option: {arg}")
        else: raise ArgumentError(f"Unexpected positional argument: {arg}")
        index += 1
    if json_seen != 1: raise ArgumentError("client update requires exactly one --json option.")
    editable_keys = {"client_name", "artist", "sample_rate", "bit_depth", "file_format", "delivery_method", "requested_deliverables"}
    if not any(key in values for key in editable_keys): raise ArgumentError("client update requires at least one editable field.")
    return ClientUpdateApiRequest(**values)
