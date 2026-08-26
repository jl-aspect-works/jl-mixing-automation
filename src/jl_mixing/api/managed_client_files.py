"""Automation API 1.0 adapters for managed Client Files import and Audio Prep reset."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import resolve_project, studio_root
from ..errors import ArgumentError, ContextError, JLMixingError, UnsafeOperationError, ValidationError
from ..managed_client_file_provenance import execute_plan, plan_import, plan_reset
from ..versions import api_version

_PROGRESS_PREFIX = "JL_PROGRESS "
_PROGRESS_MODE = "stderr-json"


@dataclass(frozen=True)
class ImportRequest:
    project: Path | None
    source_kind: str
    sources: tuple[Path, ...]
    plan_id: str | None = None
    decisions: dict[str, str] | None = None
    selected_relative_paths: tuple[str, ...] | None = None
    progress: str | None = None


@dataclass(frozen=True)
class ResetRequest:
    project: Path | None
    relative_paths: tuple[str, ...]
    plan_id: str | None = None
    decisions: dict[str, str] | None = None


def _envelope(operation: str, status: str, data: dict[str, Any], *, errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"api_version": api_version(), "operation": operation, "status": status, "data": data, "warnings": [], "errors": errors or []}


def _error(operation: str, code: str, message: str, exit_code: int, *, status: str = "error") -> dict[str, Any]:
    return _envelope(operation, status, {}, errors=[{"code": code, "message": message, "details": {"exit_code": exit_code}, "retryable": False}])


def _project_data(root: Path) -> dict[str, str]:
    return {"path": str(root), "workspace_path": str(studio_root(root))}


def _emit_progress(operation: str, event: dict[str, Any]) -> None:
    print(
        _PROGRESS_PREFIX + json.dumps({"operation": operation, **event}, separators=(",", ":"), sort_keys=True),
        file=sys.stderr,
        flush=True,
    )


def _selected_import_plan(plan: dict[str, Any], selected_relative_paths: tuple[str, ...] | None) -> dict[str, Any]:
    if selected_relative_paths is None:
        return plan
    selected = set(selected_relative_paths)
    if not selected:
        raise ValidationError("Import execute requires at least one selected relative path.")
    available = {item["relative_path"] for item in plan["files"]}
    unknown = selected - available
    if unknown:
        raise ValidationError(f"Selected import path is not part of the plan: {sorted(unknown)[0]}")
    return {
        **plan,
        "files": [item for item in plan["files"] if item["relative_path"] in selected],
        "items": [item for item in plan["items"] if item["source_relative_path"] in selected],
    }


def execute_import_plan(request: ImportRequest) -> tuple[dict[str, Any], int]:
    operation = "client.files.import.plan"
    try:
        root = resolve_project(request.project, Path.cwd())
        plan = plan_import(root, request.source_kind, request.sources)
        return _envelope(operation, "planned", {"project": _project_data(root), "plan": plan}), 0
    except ContextError as exc: return _error(operation, "PROJECT_NOT_FOUND", str(exc), exc.exit_code), exc.exit_code
    except UnsafeOperationError as exc: return _error(operation, "UNSAFE_OPERATION", str(exc), exc.exit_code, status="blocked"), exc.exit_code
    except ValidationError as exc: return _error(operation, "VALIDATION_FAILED", str(exc), exc.exit_code, status="blocked"), exc.exit_code
    except (JLMixingError, OSError) as exc:
        code = "FILESYSTEM_ERROR" if isinstance(exc, OSError) else "INTERNAL_ERROR"
        exit_code = getattr(exc, "exit_code", 1)
        return _error(operation, code, str(exc), exit_code), exit_code


def execute_import(request: ImportRequest) -> tuple[dict[str, Any], int]:
    operation = "client.files.import.execute"
    try:
        if not request.plan_id:
            raise ValidationError("Import execute requires --plan-id.")
        root = resolve_project(request.project, Path.cwd())
        full_plan = plan_import(root, request.source_kind, request.sources)
        if full_plan["plan_id"] != request.plan_id:
            raise ValidationError("Import plan is stale; run import-plan again.")
        plan = _selected_import_plan(full_plan, request.selected_relative_paths)
        progress_callback = (lambda event: _emit_progress(operation, event)) if request.progress == _PROGRESS_MODE else None
        result = execute_plan(root, plan, request.decisions or {}, progress=progress_callback)
        return _envelope(operation, "success", {"project": _project_data(root), "plan_id": full_plan["plan_id"], "result": result}), 0
    except ContextError as exc: return _error(operation, "PROJECT_NOT_FOUND", str(exc), exc.exit_code), exc.exit_code
    except UnsafeOperationError as exc: return _error(operation, "UNSAFE_OPERATION", str(exc), exc.exit_code, status="blocked"), exc.exit_code
    except ValidationError as exc: return _error(operation, "VALIDATION_FAILED", str(exc), exc.exit_code, status="blocked"), exc.exit_code
    except (JLMixingError, OSError) as exc:
        code = "FILESYSTEM_ERROR" if isinstance(exc, OSError) else "INTERNAL_ERROR"
        exit_code = getattr(exc, "exit_code", 1)
        return _error(operation, code, str(exc), exit_code), exit_code


def execute_reset_plan(request: ResetRequest) -> tuple[dict[str, Any], int]:
    operation = "audio.prep.reset.plan"
    try:
        root = resolve_project(request.project, Path.cwd())
        plan = plan_reset(root, request.relative_paths)
        return _envelope(operation, "planned", {"project": _project_data(root), "plan": plan}), 0
    except ContextError as exc: return _error(operation, "PROJECT_NOT_FOUND", str(exc), exc.exit_code), exc.exit_code
    except UnsafeOperationError as exc: return _error(operation, "UNSAFE_OPERATION", str(exc), exc.exit_code, status="blocked"), exc.exit_code
    except ValidationError as exc: return _error(operation, "VALIDATION_FAILED", str(exc), exc.exit_code, status="blocked"), exc.exit_code
    except (JLMixingError, OSError) as exc:
        code = "FILESYSTEM_ERROR" if isinstance(exc, OSError) else "INTERNAL_ERROR"
        exit_code = getattr(exc, "exit_code", 1)
        return _error(operation, code, str(exc), exit_code), exit_code


def execute_reset(request: ResetRequest) -> tuple[dict[str, Any], int]:
    operation = "audio.prep.reset.execute"
    try:
        if not request.plan_id:
            raise ValidationError("Audio Prep reset execute requires --plan-id.")
        root = resolve_project(request.project, Path.cwd())
        plan = plan_reset(root, request.relative_paths)
        if plan["plan_id"] != request.plan_id:
            raise ValidationError("Audio Prep reset plan is stale; run reset-plan again.")
        result = execute_plan(root, plan, request.decisions or {})
        return _envelope(operation, "success", {"project": _project_data(root), "plan_id": plan["plan_id"], "result": result}), 0
    except ContextError as exc: return _error(operation, "PROJECT_NOT_FOUND", str(exc), exc.exit_code), exc.exit_code
    except UnsafeOperationError as exc: return _error(operation, "UNSAFE_OPERATION", str(exc), exc.exit_code, status="blocked"), exc.exit_code
    except ValidationError as exc: return _error(operation, "VALIDATION_FAILED", str(exc), exc.exit_code, status="blocked"), exc.exit_code
    except (JLMixingError, OSError) as exc:
        code = "FILESYSTEM_ERROR" if isinstance(exc, OSError) else "INTERNAL_ERROR"
        exit_code = getattr(exc, "exit_code", 1)
        return _error(operation, code, str(exc), exit_code), exit_code


def _parse_decisions(raw: str) -> dict[str, str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ArgumentError("--decisions-json must be valid JSON.") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        raise ArgumentError("--decisions-json must be an object mapping conflict IDs to replace or skip.")
    return value


def parse_import_args(args: list[str], *, execute: bool) -> ImportRequest:
    project: Path | None = None; source_kind: str | None = None; sources: list[Path] = []
    plan_id: str | None = None; decisions: dict[str, str] | None = None; selected_relative_paths: list[str] = []; progress: str | None = None
    json_seen = 0; index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json": json_seen += 1
        elif arg.startswith("--progress="):
            value = arg.split("=", 1)[1]
            if not execute:
                raise ArgumentError("import-plan does not accept --progress.")
            if value != _PROGRESS_MODE:
                raise ArgumentError(f"Unsupported managed import progress mode: {value}. Expected {_PROGRESS_MODE}.")
            if progress is not None:
                raise ArgumentError("import-execute accepts at most one --progress option.")
            progress = value
        elif arg in {"--project", "--source-kind", "--source", "--plan-id", "--decisions-json", "--include-relative-path"}:
            index += 1
            if index >= len(args): raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--project": project = Path(value)
            elif arg == "--source-kind": source_kind = value
            elif arg == "--source": sources.append(Path(value))
            elif arg == "--plan-id": plan_id = value
            elif arg == "--include-relative-path": selected_relative_paths.append(value)
            else: decisions = _parse_decisions(value)
        else: raise ArgumentError(f"Unknown option: {arg}")
        index += 1
    if json_seen != 1: raise ArgumentError("managed import requires exactly one --json option.")
    if source_kind not in {"zip", "folder", "files"}: raise ArgumentError("--source-kind must be zip, folder, or files.")
    if not sources: raise ArgumentError("At least one --source is required.")
    if not execute and (plan_id is not None or decisions is not None or selected_relative_paths): raise ArgumentError("import-plan does not accept execute-only options.")
    if execute and plan_id is None: raise ArgumentError("import-execute requires --plan-id.")
    return ImportRequest(project, source_kind, tuple(sources), plan_id, decisions, tuple(selected_relative_paths) if selected_relative_paths else None, progress)


def parse_reset_args(args: list[str], *, execute: bool) -> ResetRequest:
    project: Path | None = None; relative_paths: list[str] = []; plan_id: str | None = None
    decisions: dict[str, str] | None = None; json_seen = 0; index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json": json_seen += 1
        elif arg in {"--project", "--relative-path", "--plan-id", "--decisions-json"}:
            index += 1
            if index >= len(args): raise ArgumentError(f"{arg} requires a value.")
            value = args[index]
            if arg == "--project": project = Path(value)
            elif arg == "--relative-path": relative_paths.append(value)
            elif arg == "--plan-id": plan_id = value
            else: decisions = _parse_decisions(value)
        else: raise ArgumentError(f"Unknown option: {arg}")
        index += 1
    if json_seen != 1: raise ArgumentError("Audio Prep reset requires exactly one --json option.")
    if not relative_paths: raise ArgumentError("At least one --relative-path is required.")
    if not execute and (plan_id is not None or decisions is not None): raise ArgumentError("reset-plan does not accept execute-only options.")
    if execute and plan_id is None: raise ArgumentError("reset-execute requires --plan-id.")
    return ResetRequest(project, tuple(relative_paths), plan_id, decisions)
