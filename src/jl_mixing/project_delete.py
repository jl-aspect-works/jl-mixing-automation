"""Authoritative, permanent project deletion by stable client and project IDs."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from .errors import ContextError, UnsafeOperationError, ValidationError
from .metadata import validate_v11
from .validation import require_slug


@dataclass(frozen=True)
class ProjectDeletePlan:
    workspace: Path
    client_path: Path
    project_path: Path
    client_id: str
    client_name: str
    project_id: str
    project_name: str
    project_document_id: str
    fingerprint: str
    file_count: int
    total_bytes: int

    def summary(self) -> dict[str, object]:
        return {
            "client": {"id": self.client_id, "name": self.client_name},
            "project": {
                "id": self.project_id,
                "name": self.project_name,
                "path": str(self.project_path),
                "document_id": self.project_document_id,
            },
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "includes": ["project metadata", "client files", "audio preparation", "DAW project", "revisions", "deliveries", "reports", "all other files inside the project directory"],
            "recoverable": False,
            "external_listening_copies": "retained",
            "fingerprint": self.fingerprint,
        }


class PartialDeletionError(OSError):
    """Deletion began but some of the project directory could not be removed."""

    def __init__(self, path: Path, reason: OSError):
        super().__init__(f"Project deletion began but cleanup failed at {path}: {reason}")
        self.path = path


def _document(path: Path, schema: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ContextError(f"Missing or unsafe {schema} document: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValidationError(f"Invalid {schema} document: {path}") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"Invalid {schema} document: {path}")
    validate_v11(data.get("metadata"), schema, mutability="mutable")
    return data


def _safe_directory(path: Path) -> bool:
    mode = path.lstat().st_mode
    return stat.S_ISDIR(mode) and not path.is_symlink() and not _is_reparse_point(path)


def _is_reparse_point(path: Path) -> bool:
    # Windows junctions are not necessarily reported as symbolic links.
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _children(parent: Path) -> list[Path]:
    try:
        return sorted(parent.iterdir(), key=lambda child: child.name)
    except OSError as exc:
        raise ContextError(f"Unable to read project ownership directory: {parent}") from exc


def _find_unique(parent: Path, marker: str, key: str, wanted: str, schema: str) -> tuple[Path, dict[str, object]]:
    matches: list[tuple[Path, dict[str, object]]] = []
    for entry in _children(parent):
        if entry.is_symlink() or _is_reparse_point(entry):
            raise UnsafeOperationError(f"Unsafe directory entry in {parent}: {entry}")
        if not _safe_directory(entry):
            continue
        path = entry.joinpath(*marker.split("/"))
        if not path.exists() and not path.is_symlink():
            continue
        document = _document(path, schema)
        if document.get(key) == wanted:
            matches.append((entry, document))
    if len(matches) > 1:
        raise ValidationError(f"Multiple {schema} documents use ID '{wanted}'.")
    if not matches:
        raise ContextError(f"{schema} not found for ID '{wanted}'.")
    return matches[0]


def _inventory(root: Path) -> tuple[str, int, int]:
    """Reject escapes/special files and fingerprint names plus file metadata."""
    digest = hashlib.sha256()
    files = 0
    total_bytes = 0
    device = root.lstat().st_dev
    pending = [root]
    while pending:
        directory = pending.pop()
        if not _safe_directory(directory) or directory.lstat().st_dev != device:
            raise UnsafeOperationError(f"Project contains an unsafe directory or mount: {directory}")
        for entry in _children(directory):
            info = entry.lstat()
            if info.st_dev != device or _is_reparse_point(entry) or stat.S_ISLNK(info.st_mode):
                raise UnsafeOperationError(f"Project contains a symlink, junction, or mount: {entry}")
            if stat.S_ISDIR(info.st_mode):
                kind = "dir"
                pending.append(entry)
            elif stat.S_ISREG(info.st_mode):
                kind = "file"
                files += 1
                total_bytes += info.st_size
            else:
                raise UnsafeOperationError(f"Project contains a special filesystem entry: {entry}")
            relative = entry.relative_to(root).as_posix()
            digest.update(json.dumps([relative, kind, info.st_size, info.st_mtime_ns], ensure_ascii=False).encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest(), files, total_bytes


def plan_project_delete(workspace: Path, client_id: str, project_id: str) -> ProjectDeletePlan:
    client_id = require_slug(client_id, label="Client ID")
    project_id = require_slug(project_id, label="Project ID")
    workspace = workspace.expanduser().absolute()
    if not workspace.exists() or not _safe_directory(workspace):
        raise ContextError(f"Workspace is missing or unsafe: {workspace}")
    # Keep the configured workspace itself link-free, then canonicalize its
    # operating-system aliases (for example Windows 8.3 paths) for stable
    # summaries and fingerprints.
    workspace = workspace.resolve(strict=True)
    studio = _document(workspace / "Studio" / "studio.json", "mixing-studio")
    if not isinstance(studio.get("studio_id"), str):
        raise ValidationError("Workspace studio identity is invalid.")
    clients = workspace / "Clients"
    if not clients.exists() or not _safe_directory(clients):
        raise ContextError(f"Workspace Clients directory is missing or unsafe: {clients}")
    client_path, client = _find_unique(clients, "client.json", "client_id", client_id, "mixing-client")
    projects = client_path / "Projects"
    if not projects.exists() or not _safe_directory(projects):
        raise ContextError(f"Client Projects directory is missing or unsafe: {projects}")
    project_path, project = _find_unique(projects, "00_Admin/project-manifest.json", "project_id", project_id, "mixing-project")
    client_metadata = client["metadata"]
    owner = project.get("client")
    if not isinstance(owner, dict) or owner.get("client_id") != client_id or owner.get("client_document_id") != client_metadata["document_id"]:
        raise ValidationError("Project manifest does not belong to the selected client.")
    client_name, project_name = client.get("client_name"), project.get("project_name")
    if not isinstance(client_name, str) or not client_name or not isinstance(project_name, str) or not project_name:
        raise ValidationError("Client or project name is invalid.")
    fingerprint, files, total_bytes = _inventory(project_path)
    fingerprint = hashlib.sha256(json.dumps([
        str(workspace), client_id, client_metadata["document_id"], client_name,
        project_id, project["metadata"]["document_id"], project_name, fingerprint,
    ], ensure_ascii=False).encode("utf-8")).hexdigest()
    return ProjectDeletePlan(
        workspace, client_path, project_path, client_id, client_name, project_id,
        project_name, project["metadata"]["document_id"], fingerprint, files, total_bytes,
    )


def execute_project_delete(workspace: Path, client_id: str, project_id: str, *,
                           fingerprint: str, confirmed_name: str) -> ProjectDeletePlan:
    if not fingerprint or not confirmed_name:
        raise ValidationError("Deletion requires a plan fingerprint and typed project name.")
    plan = plan_project_delete(workspace, client_id, project_id)
    if confirmed_name != plan.project_name or fingerprint != plan.fingerprint:
        raise ValidationError("Project identity or contents changed since the deletion summary. Review the project again.")
    # A same-filesystem rename removes the project from the active Projects
    # directory before recursive removal. Partial remnants stay in the client
    # directory and are reported explicitly, never advertised as a project.
    temporary = plan.client_path / f".deleting-{uuid.uuid4().hex}"
    if temporary.exists() or temporary.is_symlink():
        raise UnsafeOperationError(f"Deletion staging path already exists: {temporary}")
    try:
        plan.project_path.rename(temporary)
        shutil.rmtree(temporary)
    except OSError as exc:
        if temporary.exists():
            raise PartialDeletionError(temporary, exc) from exc
        raise
    return plan
