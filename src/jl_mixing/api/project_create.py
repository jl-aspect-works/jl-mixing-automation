"""Automation API 1.0 adapter for project.create."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import resolve_client_reference
from ..errors import ArgumentError, ContextError, JLMixingError, UnsafeOperationError, ValidationError
from ..project import ProjectCreateRequest, create_project
from ..versions import api_version


@dataclass(frozen=True)
class ProjectApiRequest:
    project_name: str
    client_reference: str | None = None
    project_id: str | None = None
    artist: str | None = None
    album: str = ""
    producer: str = ""
    engineer: str | None = None
    bpm: float | int | None = None
    musical_key: str = ""
    time_signature: str = ""
    sample_rate: int | None = None
    bit_depth: int | None = None
    file_format: str | None = None
    deadline: str | None = None
    deliverables: list[str] | None = None
    description: str = ""
    source: Path | None = None
    dry_run: bool = False


def _error_envelope(code: str, message: str, exit_code: int, *, status: str = "error") -> dict[str, Any]:
    return {
        "api_version": api_version(),
        "operation": "project.create",
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


def execute(request: ProjectApiRequest) -> tuple[dict[str, Any], int]:
    try:
        client_root = resolve_client_reference(request.client_reference, Path.cwd())
        result = create_project(ProjectCreateRequest(
            client_root=client_root,
            project_name=request.project_name,
            project_id=request.project_id,
            artist=request.artist,
            album=request.album,
            producer=request.producer,
            engineer=request.engineer,
            bpm=request.bpm,
            musical_key=request.musical_key,
            time_signature=request.time_signature,
            sample_rate=request.sample_rate,
            bit_depth=request.bit_depth,
            file_format=request.file_format,
            deadline=request.deadline,
            deliverables=request.deliverables,
            description=request.description,
            source=request.source,
            change_directory=False,
            dry_run=request.dry_run,
        ))
        manifest = result.manifest
        data: dict[str, Any] = {
            "project": {
                "id": manifest["project_id"],
                "name": manifest["project_name"],
                "artist": manifest["artist"],
                "path": str(result.project_root),
            },
            "manifest_path": str(result.project_root / "00_Admin" / "project-manifest.json"),
            "client_snapshot_path": str(result.project_root / "00_Admin" / "client-profile-snapshot.json"),
            "initial_revision_path": str(result.initial_revision_root),
            "client": {
                "id": manifest["client"]["client_id"],
                "path": str(result.client_root),
            },
            "workspace_path": str(result.studio_root),
        }
        if request.dry_run:
            data["would_create"] = [
                data["manifest_path"],
                data["client_snapshot_path"],
                data["initial_revision_path"],
            ]
        return {
            "api_version": api_version(),
            "operation": "project.create",
            "status": "planned" if request.dry_run else "success",
            "data": data,
            "warnings": [],
            "errors": [],
        }, 0
    except ContextError as exc:
        message = str(exc)
        lower = message.lower()
        code = "CLIENT_NOT_FOUND" if "client" in lower or "studio context" in lower else "WORKSPACE_CONTEXT_ERROR"
        return _error_envelope(code, message, exc.exit_code), exc.exit_code
    except ValidationError as exc:
        message = str(exc)
        lower = message.lower()
        code = "PROJECT_ALREADY_EXISTS" if any(token in lower for token in ("project id already exists", "path collision")) else "VALIDATION_FAILED"
        return _error_envelope(code, message, exc.exit_code, status="blocked"), exc.exit_code
    except UnsafeOperationError as exc:
        message = str(exc)
        code = "PROJECT_ALREADY_EXISTS" if "project destination already exists" in message.lower() else "UNSAFE_OPERATION"
        return _error_envelope(code, message, exc.exit_code, status="blocked"), exc.exit_code
    except JLMixingError as exc:
        return _error_envelope("INTERNAL_ERROR", str(exc), exc.exit_code), exc.exit_code
    except OSError as exc:
        return _error_envelope("FILESYSTEM_ERROR", str(exc), 1), 1


def _parse_deliverables(value: str) -> list[str]:
    raw = value.split(",")
    if not raw or any(not item.strip() for item in raw):
        raise ValidationError(f"Invalid --deliverables list: {value}")
    return [item.strip() for item in raw]


def _parse_bpm(value: str) -> float | int:
    try:
        if value.isdigit():
            return int(value)
        return float(value)
    except ValueError as exc:
        raise ValidationError(f"BPM must be a positive number: {value}") from exc


def parse_args(args: list[str]) -> ProjectApiRequest:
    project_name: str | None = None
    positional_seen = False
    project_option_seen = False
    values: dict[str, Any] = {
        "client_reference": None,
        "project_id": None,
        "artist": None,
        "album": "",
        "producer": "",
        "engineer": None,
        "bpm": None,
        "musical_key": "",
        "time_signature": "",
        "sample_rate": None,
        "bit_depth": None,
        "file_format": None,
        "deadline": None,
        "deliverables": None,
        "description": "",
        "source": None,
        "dry_run": False,
    }
    json_seen = 0
    index = 0
    option_map = {
        "--client": "client_reference",
        "--project-id": "project_id",
        "--artist": "artist",
        "--album": "album",
        "--producer": "producer",
        "--engineer": "engineer",
        "--bpm": "bpm",
        "--key": "musical_key",
        "--time-signature": "time_signature",
        "--sample-rate": "sample_rate",
        "--bit-depth": "bit_depth",
        "--file-format": "file_format",
        "--deadline": "deadline",
        "--deliverables": "deliverables",
        "--description": "description",
        "--source": "source",
    }
    while index < len(args):
        arg = args[index]
        if arg == "--json":
            json_seen += 1
        elif arg in {"--cd", "--no-cd"}:
            raise ArgumentError("project create JSON mode does not accept --cd or --no-cd.")
        elif arg == "--dry-run":
            values["dry_run"] = True
        elif arg == "--project":
            if positional_seen:
                raise ArgumentError("Project name cannot be specified both positionally and with --project.")
            index += 1
            if index >= len(args):
                raise ArgumentError("--project requires a value.")
            if project_option_seen:
                raise ArgumentError("Project name cannot be specified more than once.")
            project_name = args[index]
            project_option_seen = True
        elif arg in option_map:
            index += 1
            if index >= len(args):
                raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            field = option_map[arg]
            if arg == "--sample-rate":
                try:
                    values[field] = int(value)
                except ValueError as exc:
                    raise ValidationError(f"Unsupported sample rate: {value}") from exc
            elif arg == "--bit-depth":
                try:
                    values[field] = int(value)
                except ValueError as exc:
                    raise ValidationError(f"Unsupported bit depth: {value}") from exc
            elif arg == "--bpm":
                values[field] = _parse_bpm(value)
            elif arg == "--deliverables":
                values[field] = _parse_deliverables(value)
            elif arg == "--source":
                values[field] = Path(value)
            else:
                values[field] = value
        elif arg in {"--project-type", "--daw", "--template", "--non-interactive"}:
            raise ArgumentError(f"Removed option is not supported: {arg}")
        elif arg.startswith("-"):
            raise ArgumentError(f"Unknown option: {arg}")
        else:
            if project_option_seen:
                raise ArgumentError("Project name cannot be specified both positionally and with --project.")
            if positional_seen:
                raise ArgumentError(f"Unexpected positional argument: {arg}")
            project_name = arg
            positional_seen = True
        index += 1

    if json_seen != 1:
        raise ArgumentError("project create requires exactly one --json option.")
    if project_name is None:
        raise ArgumentError("project create requires PROJECT_NAME and --json.")
    return ProjectApiRequest(project_name=project_name, **values)
