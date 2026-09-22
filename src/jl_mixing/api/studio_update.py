"""Automation API 1.0 adapter for studio.update."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import studio_root
from ..errors import ArgumentError, ContextError, JLMixingError, UnsafeOperationError, ValidationError
from ..studio_update import StudioUpdateRequest, update_studio
from ..versions import api_version


@dataclass(frozen=True)
class StudioUpdateApiRequest:
    studio: Path | None = None
    studio_name: str | None = None
    mix_engineer: str | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    file_format: str | None = None
    delivery_method: str | None = None
    requested_deliverables: tuple[str, ...] | None = None
    dry_run: bool = False


def _error_envelope(code: str, message: str, exit_code: int, *, status: str = "error") -> dict[str, Any]:
    return {
        "api_version": api_version(),
        "operation": "studio.update",
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


def execute(request: StudioUpdateApiRequest) -> tuple[dict[str, Any], int]:
    try:
        root = studio_root(request.studio or Path.cwd())
        result = update_studio(
            StudioUpdateRequest(
                studio_root=root,
                studio_name=request.studio_name,
                mix_engineer=request.mix_engineer,
                sample_rate=request.sample_rate,
                bit_depth=request.bit_depth,
                file_format=request.file_format,
                delivery_method=request.delivery_method,
                requested_deliverables=request.requested_deliverables,
                dry_run=request.dry_run,
            )
        )
        doc = result.document
        data: dict[str, Any] = {
            "studio": {
                "id": doc["studio_id"],
                "path": str(result.studio_root),
                "configuration_path": str(result.studio_config),
            },
            "changed_fields": list(result.changed_fields),
            "editable": {
                "studio_name": doc["studio_name"],
                "mix_engineer": doc["defaults"]["mix_engineer"],
                "audio": doc["defaults"]["audio"],
                "delivery": doc["defaults"]["delivery"],
            },
            "last_modified_at": doc["metadata"]["last_modified_at"],
            "changed": bool(result.changed_fields),
        }
        if request.dry_run:
            data["would_update"] = [str(result.studio_config)] if result.changed_fields else []
        return {
            "api_version": api_version(),
            "operation": "studio.update",
            "status": "planned" if request.dry_run else "success",
            "data": data,
            "warnings": [],
            "errors": [],
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


def parse_args(args: list[str]) -> StudioUpdateApiRequest:
    values: dict[str, Any] = {"dry_run": False}
    json_seen = 0
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json":
            json_seen += 1
        elif arg == "--dry-run":
            values["dry_run"] = True
        elif arg in {
            "--studio",
            "--name",
            "--engineer",
            "--sample-rate",
            "--bit-depth",
            "--file-format",
            "--delivery-method",
            "--deliverables",
        }:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--studio":
                values["studio"] = Path(value)
            elif arg == "--name":
                values["studio_name"] = value
            elif arg == "--engineer":
                values["mix_engineer"] = value
            elif arg == "--sample-rate":
                try:
                    values["sample_rate"] = int(value)
                except ValueError as exc:
                    raise ArgumentError("--sample-rate requires an integer.") from exc
            elif arg == "--bit-depth":
                try:
                    values["bit_depth"] = int(value)
                except ValueError as exc:
                    raise ArgumentError("--bit-depth requires an integer.") from exc
            elif arg == "--file-format":
                values["file_format"] = value
            elif arg == "--delivery-method":
                values["delivery_method"] = value
            else:
                values["requested_deliverables"] = tuple(part.strip() for part in value.split(","))
        elif arg.startswith("-"):
            raise ArgumentError(f"Unknown option: {arg}")
        else:
            raise ArgumentError(f"Unexpected positional argument: {arg}")
        index += 1
    if json_seen != 1:
        raise ArgumentError("studio update requires exactly one --json option.")
    editable_keys = {
        "studio_name",
        "mix_engineer",
        "sample_rate",
        "bit_depth",
        "file_format",
        "delivery_method",
        "requested_deliverables",
    }
    if not any(key in values for key in editable_keys):
        raise ArgumentError("studio update requires at least one editable field.")
    return StudioUpdateApiRequest(**values)
