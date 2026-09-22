"""Automation API 1.0 adapter for client.create."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..client import ClientCreateRequest, create_client
from ..context import studio_root
from ..errors import ArgumentError, ContextError, JLMixingError, UnsafeOperationError, ValidationError
from ..versions import api_version


@dataclass(frozen=True)
class ClientApiRequest:
    client_id: str
    studio: str | None = None
    client_name: str | None = None
    artist: str = ""
    sample_rate: int | None = None
    bit_depth: int | None = None
    file_format: str | None = None
    delivery_method: str | None = None
    deliverables: list[str] | None = None
    dry_run: bool = False


def _error_envelope(code: str, message: str, exit_code: int, *, status: str = "error") -> dict[str, Any]:
    return {
        "api_version": api_version(),
        "operation": "client.create",
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


def execute(request: ClientApiRequest) -> tuple[dict[str, Any], int]:
    try:
        context = Path(request.studio) if request.studio is not None else Path.cwd()
        workspace = studio_root(context)
        result = create_client(ClientCreateRequest(
            studio_root=workspace,
            client_id=request.client_id,
            client_name=request.client_name,
            artist=request.artist,
            sample_rate=request.sample_rate,
            bit_depth=request.bit_depth,
            file_format=request.file_format,
            delivery_method=request.delivery_method,
            deliverables=request.deliverables,
            dry_run=request.dry_run,
        ))
        data: dict[str, Any] = {
            "client": {"id": request.client_id, "path": str(result.client_root)},
            "configuration_path": str(result.client_root / "client.json"),
            "workspace_path": str(workspace),
        }
        if request.dry_run:
            data["would_create"] = [
                str(result.client_root / "client.json"),
                str(result.client_root / "Projects"),
            ]
        return {
            "api_version": api_version(),
            "operation": "client.create",
            "status": "planned" if request.dry_run else "success",
            "data": data,
            "warnings": [],
            "errors": [],
        }, 0
    except ContextError as exc:
        return _error_envelope("WORKSPACE_CONTEXT_ERROR", str(exc), exc.exit_code), exc.exit_code
    except ValidationError as exc:
        message = str(exc)
        code = "CLIENT_ALREADY_EXISTS" if any(token in message.lower() for token in ("already exists", "collision")) else "VALIDATION_FAILED"
        return _error_envelope(code, message, exc.exit_code, status="blocked"), exc.exit_code
    except UnsafeOperationError as exc:
        message = str(exc)
        code = "CLIENT_ALREADY_EXISTS" if "already exists" in message.lower() else "UNSAFE_OPERATION"
        return _error_envelope(code, message, exc.exit_code, status="blocked"), exc.exit_code
    except JLMixingError as exc:
        return _error_envelope("INTERNAL_ERROR", str(exc), exc.exit_code), exc.exit_code


def _parse_deliverables(value: str) -> list[str]:
    raw = value.split(",")
    if not raw or any(not item.strip() for item in raw):
        raise ValidationError(f"Invalid --deliverables list: {value}")
    return [item.strip() for item in raw]


def parse_args(args: list[str]) -> ClientApiRequest:
    if not args or args[0].startswith("-"):
        raise ArgumentError("client create requires CLIENT_ID and --json.")
    client_id = args[0]
    studio: str | None = None
    client_name: str | None = None
    artist = ""
    sample_rate: int | None = None
    bit_depth: int | None = None
    file_format: str | None = None
    delivery_method: str | None = None
    deliverables: list[str] | None = None
    dry_run = False
    json_seen = 0
    index = 1
    while index < len(args):
        arg = args[index]
        if arg == "--json":
            json_seen += 1
        elif arg in {"--cd", "--no-cd"}:
            raise ArgumentError("client create JSON mode does not accept --cd or --no-cd.")
        elif arg in {"--studio", "--name", "--artist", "--sample-rate", "--bit-depth", "--file-format", "--delivery-method", "--deliverables"}:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--studio":
                if not value.strip():
                    raise ArgumentError("--studio requires a non-empty path.")
                studio = value
            elif arg == "--name":
                client_name = value
            elif arg == "--artist":
                artist = value
            elif arg == "--sample-rate":
                try:
                    sample_rate = int(value)
                except ValueError as exc:
                    raise ValidationError(f"Unsupported sample rate: {value}") from exc
            elif arg == "--bit-depth":
                try:
                    bit_depth = int(value)
                except ValueError as exc:
                    raise ValidationError(f"Unsupported bit depth: {value}") from exc
            elif arg == "--file-format":
                file_format = value
            elif arg == "--delivery-method":
                delivery_method = value
            else:
                deliverables = _parse_deliverables(value)
        elif arg == "--dry-run":
            dry_run = True
        elif arg.startswith("-"):
            raise ArgumentError(f"Unknown option: {arg}")
        else:
            raise ArgumentError(f"Unexpected positional argument: {arg}")
        index += 1
    if json_seen != 1:
        raise ArgumentError("client create requires exactly one --json option.")
    return ClientApiRequest(
        client_id=client_id,
        studio=studio,
        client_name=client_name,
        artist=artist,
        sample_rate=sample_rate,
        bit_depth=bit_depth,
        file_format=file_format,
        delivery_method=delivery_method,
        deliverables=deliverables,
        dry_run=dry_run,
    )
