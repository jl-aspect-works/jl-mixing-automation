"""Version and installed-resource discovery for JL Mixing Automation."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
_API_VERSION = re.compile(r"^[0-9]+\.[0-9]+$")


def application_root() -> Path:
    """Return the installed application root.

    JL_MIXING_HOME remains supported for compatibility with the v1.4 launch and
    test environment. Frozen release runtimes infer the application root from
    their executable location under ``runtime/``. Source/development execution
    otherwise resolves from the package layout.
    """

    override = os.environ.get("JL_MIXING_HOME")
    if override:
        return Path(override).expanduser().resolve()

    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        runtime_parent = executable.parent.parent
        if (runtime_parent / "VERSION").is_file() and (runtime_parent / "API_VERSION").is_file():
            return runtime_parent

    return Path(__file__).resolve().parents[2]


def _read_first_line(path: Path, label: str) -> str:
    try:
        value = path.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError) as exc:
        raise RuntimeError(f"Unable to read {label}: {path}") from exc
    if not value:
        raise RuntimeError(f"Empty {label}: {path}")
    return value


def application_version() -> str:
    version_file = Path(os.environ.get("JL_MIXING_VERSION_FILE", application_root() / "VERSION"))
    value = _read_first_line(version_file, "application version")
    if not _SEMVER.fullmatch(value):
        raise RuntimeError(f"Invalid application version: {value}")
    return value


def api_version() -> str:
    version_file = Path(os.environ.get("JL_MIXING_API_VERSION_FILE", application_root() / "API_VERSION"))
    value = _read_first_line(version_file, "Automation API version")
    if not _API_VERSION.fullmatch(value):
        raise RuntimeError(f"Invalid Automation API version: {value}")
    return value


def schema_root() -> Path:
    path = application_root() / "api" / "schemas" / f"v{api_version()}"
    if not path.is_dir():
        raise RuntimeError(f"Automation API schemas are not installed: {path}")
    return path
