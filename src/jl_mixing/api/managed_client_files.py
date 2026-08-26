"""Automation API 1.0 adapters for managed Client Files import and Audio Prep reset."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context import resolve_project, studio_root
from ..diagnostic_log import debug as log_debug
from ..diagnostic_log import error as log_error
from ..diagnostic_log import info as log_info
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
    log_error("operation_error", operation=operation, code=code, exit_code=exit_code, message=message)
    return _envelope(operation, status, {}, errors=[{"code": code, "message": message, "details": {"exit_code": exit_code}, "retryable": False}])


def _project_data(root: Path) -> dict[str, str]:
    return {"path": str(root), "workspace_path": str(studio_root(root))}


def _emit_progress(operation: str, event: dict[str, Any]) -> None:
    log_debug("progress_emit", operation=operation, **event)
    print(
        _PROGRESS_PREFIX + json.dumps({"operation": operation, **event}, separators=(",", ":"), sort_keys=True),
        file=sys.stderr,
        flush=True,
    )


class _ImportProgressAdapter:
    """Translate phase-local engine progress into an additive monotonic import contract."""

    def __init__(self, operation: str, total_files: int):
        self.operation = operation
        self.total_files = total_files
        self.overall_total = total_files * 2 + 1
        self.staging_seen = 0
        self.staging_complete_emitted = False
        self.finalizing_emitted = False

    def _emit(self, phase: str, completed: int, active: list[str], overall_completed: int) -> None:
        _emit_progress(
            self.operation,
            {
                "phase": phase,
                "completed": completed,
                "total": self.total_files,
                "overall_completed": overall_completed,
                "overall_total": self.overall_total,
                "active": active,
            },
        )

    def _finish_staging(self) -> None:
        if not self.staging_complete_emitted:
            self._emit("staging", self.total_files, [], self.total_files)
            self.staging_complete_emitted = True

    def __call__(self, event: dict[str, Any]) -> None:
        phase = str(event.get("phase", ""))
        active = [str(value) for value in event.get("active", [])]
        completed = max(0, min(int(event.get("completed", 0)), self.total_files))

        if phase == "staging":
            stage_completed = min(self.staging_seen, self.total_files)
            self._emit("staging", stage_completed, active, stage_completed)
            self.staging_seen += 1
            return

        if phase == "importing":
            self._finish_staging()
            self._emit("importing", completed, active, self.total_files + completed)
            return

        if phase == "complete":
            self._finish_staging()
            self._emit("finalizing", self.total_files, [], self.total_files * 2)
            self.finalizing_emitted = True
            return

        _emit_progress(self.operation, event)

    def finish(self) -> None:
        self._finish_staging()
        if not self.finalizing_emitted:
            self._emit("finalizing", self.total_files, [], self.total_files * 2)
            self.finalizing_emitted = True
        self._emit("complete", self.total_files, [], self.overall_total)


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
    started = time.monotonic()
    log_info("operation_start", operation=operation, source_kind=request.source_kind, source_count=len(request.sources))
    try:
        root = resolve_project(request.project, Path.cwd())
        plan = plan_import(root, request.source_kind, request.sources)
        log_info("operation_complete", operation=operation, duration_ms=int((time.monotonic() - started) * 1000), file_count=len(plan.get("files", [])))
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
    started = time.monotonic()
    log_info(
        "operation_start",
        operation=operation,
        source_kind=request.source_kind,
        source_count=len(request.sources),
        selected_count=len(request.selected_relative_paths or ()),
        progress_mode=request.progress,
    )
    try:
        if not request.plan_id:
            raise ValidationError("Import execute requires --plan-id.")
        root = resolve_project(request.project, Path.cwd())
        progress_enabled = request.progress == _PROGRESS_MODE
        log_info("progress_mode", operation=operation, streaming=progress_enabled)
        if progress_enabled:
            _emit_progress(
                operation,
                {
                    "phase": "planning",
                    "completed": 0,
                    "total": None,
                    "overall_completed": 0,
                    "overall_total": None,
                    "active": [],
                },
            )
        plan_started = time.monotonic()
        full_plan = plan_import(root, request.source_kind, request.sources)
        log_info(
            "import_replan_complete",
            operation=operation,
            duration_ms=int((time.monotonic() - plan_started) * 1000),
            file_count=len(full_plan.get("files", [])),
        )
        if full_plan["plan_id"] != request.plan_id:
            raise ValidationError("Import plan is stale; run import-plan again.")
        plan = _selected_import_plan(full_plan, request.selected_relative_paths)
        progress_adapter = _ImportProgressAdapter(operation, len(plan["files"])) if progress_enabled else None
        result = execute_plan(root, plan, request.decisions or {}, progress=progress_adapter)
        if progress_adapter is not None:
            progress_adapter.finish()
        log_info(
            "operation_complete",
            operation=operation,
            duration_ms=int((time.monotonic() - started) * 1000),
            selected_count=len(plan.get("files", [])),
        )
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
