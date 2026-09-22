"""Automation API 1.0 adapters for managed delivery status and package deletion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..delivery_management import (
    DeliveryDeletePackageRequest,
    DeliveryStatusRequest,
    delete_generated_package,
    inspect_delivery,
)
from ..delivery_requirements import reconcile_delivery_requirements
from ..errors import ArgumentError, ContextError, JLMixingError, UnsafeOperationError, ValidationError
from ..versions import api_version


@dataclass(frozen=True)
class DeliveryStatusApiRequest:
    project: Path


@dataclass(frozen=True)
class DeliveryDeletePackageApiRequest:
    project: Path
    zip_name: str


def _error_envelope(operation: str, code: str, message: str, exit_code: int, *, status: str = "error") -> dict[str, Any]:
    return {
        "api_version": api_version(),
        "operation": operation,
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


def execute_status(request: DeliveryStatusApiRequest) -> tuple[dict[str, Any], int]:
    operation = "delivery.status"
    try:
        data = inspect_delivery(DeliveryStatusRequest(request.project))
        data = reconcile_delivery_requirements(Path(data["project"]["path"]), data)
        return {
            "api_version": api_version(),
            "operation": operation,
            "status": "success",
            "data": data,
            "warnings": [],
            "errors": [],
        }, 0
    except ContextError as exc:
        return _error_envelope(operation, "PROJECT_NOT_FOUND", str(exc), exc.exit_code), exc.exit_code
    except UnsafeOperationError as exc:
        return _error_envelope(operation, "UNSAFE_DELIVERY_OPERATION", str(exc), exc.exit_code, status="blocked"), exc.exit_code
    except ValidationError as exc:
        return _error_envelope(operation, "DELIVERY_VALIDATION_FAILED", str(exc), exc.exit_code, status="blocked"), exc.exit_code
    except JLMixingError as exc:
        return _error_envelope(operation, "INTERNAL_ERROR", str(exc), exc.exit_code), exc.exit_code


def execute_delete_package(request: DeliveryDeletePackageApiRequest) -> tuple[dict[str, Any], int]:
    operation = "delivery.delete-package"
    try:
        data = delete_generated_package(DeliveryDeletePackageRequest(request.project, request.zip_name))
        return {
            "api_version": api_version(),
            "operation": operation,
            "status": "success",
            "data": data,
            "warnings": [],
            "errors": [],
        }, 0
    except ContextError as exc:
        return _error_envelope(operation, "PROJECT_NOT_FOUND", str(exc), exc.exit_code), exc.exit_code
    except UnsafeOperationError as exc:
        return _error_envelope(operation, "UNSAFE_DELIVERY_OPERATION", str(exc), exc.exit_code, status="blocked"), exc.exit_code
    except ValidationError as exc:
        return _error_envelope(operation, "DELIVERY_VALIDATION_FAILED", str(exc), exc.exit_code, status="blocked"), exc.exit_code
    except JLMixingError as exc:
        return _error_envelope(operation, "INTERNAL_ERROR", str(exc), exc.exit_code), exc.exit_code


def parse_status_args(args: list[str]) -> DeliveryStatusApiRequest:
    project: Path | None = None
    json_seen = 0
    project_seen = 0
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json":
            json_seen += 1
        elif arg == "--project":
            index += 1
            if index >= len(args):
                raise ArgumentError("--project requires a value.")
            project_seen += 1
            project = Path(args[index])
        elif arg.startswith("-"):
            raise ArgumentError(f"Unknown option: {arg}")
        else:
            raise ArgumentError(f"Unexpected positional argument: {arg}")
        index += 1
    if json_seen != 1 or project_seen != 1 or project is None or str(project) == "":
        raise ArgumentError("delivery status requires exactly one --json option and one explicit --project PATH.")
    return DeliveryStatusApiRequest(project)


def parse_delete_package_args(args: list[str]) -> DeliveryDeletePackageApiRequest:
    project: Path | None = None
    zip_name: str | None = None
    json_seen = 0
    project_seen = 0
    zip_seen = 0
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json":
            json_seen += 1
        elif arg in {"--project", "--zip-name"}:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--project":
                project_seen += 1
                project = Path(value)
            else:
                zip_seen += 1
                zip_name = value
        elif arg.startswith("-"):
            raise ArgumentError(f"Unknown option: {arg}")
        else:
            raise ArgumentError(f"Unexpected positional argument: {arg}")
        index += 1
    if json_seen != 1 or project_seen != 1 or project is None or str(project) == "":
        raise ArgumentError("delivery delete-package requires exactly one --json option and one explicit --project PATH.")
    if zip_seen != 1 or zip_name is None or not zip_name:
        raise ArgumentError("delivery delete-package requires exactly one --zip-name NAME.")
    return DeliveryDeletePackageApiRequest(project, zip_name)
