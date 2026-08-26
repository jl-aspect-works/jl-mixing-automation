"""Lightweight file-based structured diagnostics.

Diagnostics never write to stdout/stderr so API and progress contracts stay clean.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_MAX_BYTES = 5 * 1024 * 1024
_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}


def _configured_level() -> int:
    return _LEVELS.get(os.environ.get("JL_MIXING_LOG_LEVEL", "info").strip().lower(), 20)


def log_path() -> Path:
    override = os.environ.get("JL_MIXING_LOG_DIR")
    if override:
        root = Path(override).expanduser()
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / "JL Mixing" / "logs"
    else:
        state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        root = state / "jl-mixing" / "logs"
    return root / "automation.jsonl"


def _rotate(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size >= _MAX_BYTES:
            rotated = path.with_suffix(path.suffix + ".1")
            if rotated.exists():
                rotated.unlink()
            path.replace(rotated)
    except OSError:
        pass


def log(level: str, event: str, **fields: Any) -> None:
    normalized = level.lower()
    if _LEVELS.get(normalized, 20) < _configured_level():
        return
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate(path)
        record = {
            "ts_unix_ms": int(time.time() * 1000),
            "level": normalized,
            "component": "automation",
            "event": event,
            **fields,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":"), sort_keys=True, default=str) + "\n")
    except OSError:
        # Diagnostics must never break an Automation operation.
        pass


def debug(event: str, **fields: Any) -> None:
    log("debug", event, **fields)


def info(event: str, **fields: Any) -> None:
    log("info", event, **fields)


def error(event: str, **fields: Any) -> None:
    log("error", event, **fields)
