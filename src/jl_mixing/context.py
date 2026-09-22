"""Cross-platform studio, client, project, and revision context discovery."""

from __future__ import annotations

import json
from pathlib import Path

from .errors import ArgumentError, ContextError, ValidationError
from .paths import native_absolute_path
from .validation import require_slug


def _read_json(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Invalid JSON document: {path}") from exc


def _require_identity(path: Path, schema: str, version: str = "1.1.0") -> None:
    if path.is_symlink() or not path.is_file():
        raise ContextError(f"Required context marker not found or unsafe: {path}")
    document = _read_json(path)
    metadata = document.get("metadata")
    if not isinstance(metadata, dict):
        raise ValidationError(f"Missing metadata in: {path}")
    if metadata.get("schema") != schema or metadata.get("schema_version") != version:
        raise ValidationError(f"Unexpected schema identity in: {path}")


def find_up_safe(start: Path | str, relative_marker: str) -> Path:
    current = native_absolute_path(start, base=Path.cwd())
    if not current.is_dir():
        current = current.parent
    while True:
        marker = current.joinpath(*relative_marker.split("/"))
        if marker.is_file() and not marker.is_symlink():
            return current
        if current.parent == current:
            break
        current = current.parent
    raise ContextError(f"No context marker '{relative_marker}' found from: {start}")


def project_root(start: Path | str) -> Path:
    root = find_up_safe(start, "00_Admin/project-manifest.json")
    _require_identity(root / "00_Admin" / "project-manifest.json", "mixing-project")
    return root


def client_root(start: Path | str) -> Path:
    root = find_up_safe(start, "client.json")
    _require_identity(root / "client.json", "mixing-client")
    return root


def studio_root(start: Path | str) -> Path:
    root = find_up_safe(start, "Studio/studio.json")
    _require_identity(root / "Studio" / "studio.json", "mixing-studio")
    return root


def resolve_project(explicit: Path | str | None, start: Path | str) -> Path:
    if explicit is None or str(explicit) == "":
        return project_root(start)
    candidate = native_absolute_path(explicit, base=native_absolute_path(start, base=Path.cwd()))
    if candidate.is_file() and candidate.name == "project-manifest.json":
        candidate = candidate.parent.parent
    manifest = candidate / "00_Admin" / "project-manifest.json"
    if candidate.is_symlink() or manifest.is_symlink() or not manifest.is_file():
        raise ContextError(f"Project not found or unsafe at explicit path: {explicit}")
    _require_identity(manifest, "mixing-project")
    return candidate


def resolve_client(explicit: Path | str | None, start: Path | str) -> Path:
    if explicit is None or str(explicit) == "":
        return client_root(start)
    candidate = native_absolute_path(explicit, base=native_absolute_path(start, base=Path.cwd()))
    if candidate.is_file() and candidate.name == "client.json":
        candidate = candidate.parent
    marker = candidate / "client.json"
    if candidate.is_symlink() or marker.is_symlink() or not marker.is_file():
        raise ContextError(f"Client not found or unsafe at explicit path: {explicit}")
    _require_identity(marker, "mixing-client")
    return candidate


def resolve_client_reference(reference: str | Path | None, start: Path | str) -> Path:
    """Resolve a v1.4 new-mix client reference by context, path, or stable ID."""

    if reference is None or str(reference) == "":
        try:
            return client_root(start)
        except ContextError as exc:
            raise ContextError(
                "Run new-mix inside a client directory or supply --client CLIENT_ID_OR_PATH."
            ) from exc

    text = str(reference)
    base = native_absolute_path(start, base=Path.cwd())
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    if candidate.exists() or candidate.is_symlink():
        return resolve_client(candidate, start)

    client_id = require_slug(text, label="Client ID")
    try:
        studio = studio_root(start)
    except ContextError as exc:
        raise ContextError(f"A studio context is required to resolve client ID '{client_id}'.") from exc

    matches: list[Path] = []
    for client_file in (studio / "Clients").glob("*/client.json"):
        if client_file.is_symlink() or not client_file.is_file():
            continue
        document = _read_json(client_file)
        if document.get("client_id") == client_id:
            matches.append(client_file.parent)
    if len(matches) == 1:
        _require_identity(matches[0] / "client.json", "mixing-client")
        return matches[0]
    if len(matches) > 1:
        raise ValidationError(f"Multiple clients use the ID '{client_id}'.")
    raise ContextError(f"Client not found: {client_id}")


def revision_root_for_number(project: Path, number: int) -> Path:
    if not isinstance(number, int) or number < 1:
        raise ArgumentError(f"Invalid revision number: {number}")
    root = project / "04_Revisions" / f"Revision_{number:02d}"
    if root.is_symlink() or not root.is_dir():
        raise ContextError(f"Revision directory not found or unsafe: {root}")
    return root
