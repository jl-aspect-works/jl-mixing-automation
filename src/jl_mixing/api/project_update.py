"""Automation API 1.0 adapter for project.update."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import resolve_project, studio_root
from ..errors import ArgumentError, ContextError, JLMixingError, UnsafeOperationError, ValidationError
from ..project_update import ProjectUpdateRequest, update_project
from ..versions import api_version


@dataclass(frozen=True)
class ProjectUpdateApiRequest:
    project: Path | None = None
    project_name: str | None = None
    artist: str | None = None
    album: str | None = None
    producer: str | None = None
    mix_engineer: str | None = None
    bpm_set: bool = False
    bpm: float | int | None = None
    musical_key: str | None = None
    time_signature: str | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    file_format: str | None = None
    delivery_method: str | None = None
    requested_deliverables: tuple[str, ...] | None = None
    deadline_set: bool = False
    deadline: str | None = None
    creative_direction: str | None = None
    dry_run: bool = False


def _error_envelope(code: str, message: str, exit_code: int, *, status: str = "error") -> dict[str, Any]:
    return {"api_version": api_version(), "operation": "project.update", "status": status, "data": {}, "warnings": [], "errors": [{"code": code, "message": message, "details": {"exit_code": exit_code}, "retryable": False}]}


def execute(request: ProjectUpdateApiRequest) -> tuple[dict[str, Any], int]:
    try:
        root = resolve_project(request.project, Path.cwd())
        result = update_project(ProjectUpdateRequest(
            project_root=root, project_name=request.project_name, artist=request.artist,
            album=request.album, producer=request.producer, mix_engineer=request.mix_engineer,
            bpm_set=request.bpm_set, bpm=request.bpm, musical_key=request.musical_key,
            time_signature=request.time_signature, sample_rate=request.sample_rate,
            bit_depth=request.bit_depth, file_format=request.file_format,
            delivery_method=request.delivery_method, requested_deliverables=request.requested_deliverables,
            deadline_set=request.deadline_set, deadline=request.deadline,
            creative_direction=request.creative_direction, dry_run=request.dry_run,
        ))
        doc=result.document
        data: dict[str, Any] = {
            "project":{"id":doc["project_id"],"path":str(result.project_root),"manifest_path":str(result.manifest_path)},
            "workspace_path":str(studio_root(result.project_root)),
            "changed_fields":list(result.changed_fields), "invalidations":list(result.invalidations),
            "editable":{"project_name":doc["project_name"],"artist":doc["artist"],"album":doc["album"],"producer":doc["producer"],"mix_engineer":doc["mix_engineer"],"music":doc["music"],"audio":doc["audio"],"delivery":doc["delivery"],"schedule":doc["schedule"],"creative_direction":doc["creative_direction"]},
            "last_modified_at":doc["metadata"]["last_modified_at"], "changed":bool(result.changed_fields),
        }
        if request.dry_run: data["would_update"]=[str(result.manifest_path)] if result.changed_fields else []
        return {"api_version":api_version(),"operation":"project.update","status":"planned" if request.dry_run else "success","data":data,"warnings":[],"errors":[]},0
    except ContextError as exc: return _error_envelope("PROJECT_NOT_FOUND",str(exc),exc.exit_code),exc.exit_code
    except UnsafeOperationError as exc: return _error_envelope("UNSAFE_OPERATION",str(exc),exc.exit_code,status="blocked"),exc.exit_code
    except ValidationError as exc: return _error_envelope("VALIDATION_FAILED",str(exc),exc.exit_code,status="blocked"),exc.exit_code
    except JLMixingError as exc: return _error_envelope("INTERNAL_ERROR",str(exc),exc.exit_code),exc.exit_code
    except OSError as exc: return _error_envelope("FILESYSTEM_ERROR",str(exc),1),1


def _nullable(value: str) -> str | None:
    return None if value.strip().lower() in {"", "null", "none"} else value


def parse_args(args: list[str]) -> ProjectUpdateApiRequest:
    values: dict[str, Any]={"dry_run":False,"bpm_set":False,"deadline_set":False}; json_seen=0; index=0
    options={"--project","--name","--artist","--album","--producer","--engineer","--bpm","--key","--time-signature","--sample-rate","--bit-depth","--file-format","--delivery-method","--deliverables","--deadline","--creative-direction"}
    while index < len(args):
        arg=args[index]
        if arg=="--json": json_seen+=1
        elif arg=="--dry-run": values["dry_run"]=True
        elif arg in options:
            index+=1
            if index>=len(args): raise ArgumentError(f"{arg} requires a value.")
            value=args[index]
            if arg=="--project": values["project"]=Path(value)
            elif arg=="--name": values["project_name"]=value
            elif arg=="--artist": values["artist"]=value
            elif arg=="--album": values["album"]=value
            elif arg=="--producer": values["producer"]=value
            elif arg=="--engineer": values["mix_engineer"]=value
            elif arg=="--bpm":
                values["bpm_set"]=True; nullable=_nullable(value)
                if nullable is None: values["bpm"]=None
                else:
                    try: values["bpm"]=float(nullable)
                    except ValueError as exc: raise ArgumentError("--bpm requires a positive number or null.") from exc
            elif arg=="--key": values["musical_key"]=value
            elif arg=="--time-signature": values["time_signature"]=value
            elif arg=="--sample-rate":
                try: values["sample_rate"]=int(value)
                except ValueError as exc: raise ArgumentError("--sample-rate requires an integer.") from exc
            elif arg=="--bit-depth":
                try: values["bit_depth"]=int(value)
                except ValueError as exc: raise ArgumentError("--bit-depth requires an integer.") from exc
            elif arg=="--file-format": values["file_format"]=value
            elif arg=="--delivery-method": values["delivery_method"]=value
            elif arg=="--deliverables": values["requested_deliverables"]=tuple(part.strip() for part in value.split(","))
            elif arg=="--deadline": values["deadline_set"]=True; values["deadline"]=_nullable(value)
            else: values["creative_direction"]=value
        elif arg.startswith("-"): raise ArgumentError(f"Unknown option: {arg}")
        else: raise ArgumentError(f"Unexpected positional argument: {arg}")
        index+=1
    if json_seen!=1: raise ArgumentError("project update requires exactly one --json option.")
    editable={"project_name","artist","album","producer","mix_engineer","bpm_set","musical_key","time_signature","sample_rate","bit_depth","file_format","delivery_method","requested_deliverables","deadline_set","creative_direction"}
    if not any((key in values and (key not in {"bpm_set","deadline_set"} or values[key])) for key in editable): raise ArgumentError("project update requires at least one editable field.")
    return ProjectUpdateApiRequest(**values)
