"""Automation API 1.0 adapter for delivery.create."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import studio_root
from ..delivery import DeliveryCreateRequest, create_delivery
from ..errors import ArgumentError, ContextError, JLMixingError, UnsafeOperationError, ValidationError
from ..versions import api_version


@dataclass(frozen=True)
class DeliveryCreateApiRequest:
    project: Path
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    working_prefix: str = "WORK "
    overwrite: bool = False
    clean: bool = False
    make_zip: bool = False
    dry_run: bool = False


def _error_envelope(code: str, message: str, exit_code: int, *, status: str = "error") -> dict[str, Any]:
    return {
        "api_version": api_version(),
        "operation": "delivery.create",
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


def execute(request: DeliveryCreateApiRequest) -> tuple[dict[str, Any], int]:
    try:
        result = create_delivery(DeliveryCreateRequest(
            project_root=request.project,
            include=request.include,
            exclude=request.exclude,
            working_prefix=request.working_prefix,
            overwrite=request.overwrite,
            clean=request.clean,
            make_zip=request.make_zip,
            dry_run=request.dry_run,
        ))
        manifest_path = result.project_root / "00_Admin" / "project-manifest.json"
        delivery_notes_path = result.delivery_root / "Delivery_Notes.md"
        delivery_manifest_path = result.delivery_root / "delivery-manifest.json"
        workspace = studio_root(result.project_root)
        data: dict[str, Any] = {
            "project": {
                "id": result.manifest.get("project_id", ""),
                "name": result.manifest.get("project_name", ""),
                "path": str(result.project_root),
            },
            "revision": {
                "number": result.approved_revision,
                "path": str(result.revision_root),
            },
            "current_revision": result.current_revision,
            "approved_revision": result.approved_revision,
            "delivered_revision": None if request.dry_run else result.approved_revision,
            "delivery_method": result.delivery_method,
            "replacement_mode": result.plan.mode,
            "zip_requested": request.make_zip,
            "zip_name": result.zip_name,
            "selected": [
                {
                    "source_name": item.name,
                    "deliverable_type": item.deliverable_type,
                    "path": item.path,
                }
                for item in result.plan.selected
            ],
            "excluded": [
                {"name": item.name, "reason": item.reason}
                for item in result.plan.excluded
            ],
            "deletions": list(result.plan.deletions),
            "manifest_path": str(manifest_path),
            "delivery_path": str(result.delivery_root),
            "delivery_notes_path": str(delivery_notes_path),
            "delivery_manifest_path": str(delivery_manifest_path),
            "workspace_path": str(workspace),
            "files_delivered": 0 if request.dry_run else result.files_delivered,
        }
        if result.zip_name is not None:
            data["zip_path"] = str(result.delivery_root / result.zip_name)
        if request.dry_run:
            data["would_update"] = [str(manifest_path), str(result.delivery_root)]
        return {
            "api_version": api_version(),
            "operation": "delivery.create",
            "status": "planned" if request.dry_run else "success",
            "data": data,
            "warnings": [],
            "errors": [],
        }, 0
    except ContextError as exc:
        return _error_envelope("PROJECT_NOT_FOUND", str(exc), exc.exit_code), exc.exit_code
    except UnsafeOperationError as exc:
        return _error_envelope("UNSAFE_DELIVERY_OPERATION", str(exc), exc.exit_code, status="blocked"), exc.exit_code
    except ValidationError as exc:
        message = str(exc)
        lowered = message.lower()
        if "must be approved" in lowered or "approved revision" in lowered:
            code = "REVISION_NOT_APPROVED"
        elif "overwrite" in lowered or "already exists" in lowered or "replacement" in lowered:
            code = "DELIVERY_REPLACEMENT_REQUIRED"
        elif "unsafe" in lowered or "clean" in lowered or "symbolic link" in lowered:
            code = "UNSAFE_DELIVERY_OPERATION"
        else:
            code = "DELIVERY_VALIDATION_FAILED"
        return _error_envelope(code, message, exc.exit_code, status="blocked"), exc.exit_code
    except JLMixingError as exc:
        return _error_envelope("INTERNAL_ERROR", str(exc), exc.exit_code), exc.exit_code


def parse_args(args: list[str]) -> DeliveryCreateApiRequest:
    project: Path | None = None
    includes: list[str] = []
    excludes: list[str] = []
    working_prefix = "WORK "
    overwrite = False
    clean = False
    make_zip = False
    dry_run = False
    json_seen = 0
    project_seen = 0
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json":
            json_seen += 1
        elif arg in {"--project", "--include", "--exclude", "--working-prefix"}:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--project":
                project_seen += 1
                project = Path(value)
            elif arg == "--include":
                if not value.strip():
                    raise ArgumentError("--include cannot be empty.")
                includes.append(value)
            elif arg == "--exclude":
                if not value.strip():
                    raise ArgumentError("--exclude cannot be empty.")
                excludes.append(value)
            else:
                if value == "":
                    raise ArgumentError("--working-prefix cannot be empty.")
                working_prefix = value
        elif arg == "--overwrite":
            overwrite = True
        elif arg == "--clean":
            clean = True
        elif arg == "--zip":
            make_zip = True
        elif arg == "--dry-run":
            dry_run = True
        elif arg in {"--revision", "--checksum", "--mark-delivered", "--non-interactive"}:
            raise ArgumentError(f"Unknown option: {arg}")
        elif arg.startswith("-"):
            raise ArgumentError(f"Unknown option: {arg}")
        else:
            raise ArgumentError(f"Unexpected positional argument: {arg}")
        index += 1

    if json_seen != 1 or project_seen != 1 or project is None or str(project) == "":
        raise ArgumentError("delivery create requires exactly one --json option and one explicit --project PATH.")
    if overwrite and clean:
        raise ArgumentError("--overwrite and --clean are mutually exclusive.")
    return DeliveryCreateApiRequest(
        project=project,
        include=tuple(includes),
        exclude=tuple(excludes),
        working_prefix=working_prefix,
        overwrite=overwrite,
        clean=clean,
        make_zip=make_zip,
        dry_run=dry_run,
    )
