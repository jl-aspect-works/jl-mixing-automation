"""Authoritative, permanent deletion of project-free clients by stable ID."""

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
class ClientDeletePlan:
    workspace: Path
    client_path: Path
    client_id: str
    client_name: str
    client_document_id: str
    fingerprint: str
    file_count: int
    total_bytes: int

    def summary(self) -> dict[str, object]:
        return {
            "client": {
                "id": self.client_id,
                "name": self.client_name,
                "path": str(self.client_path),
                "document_id": self.client_document_id,
            },
            "project_count": 0,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "includes": [
                "client metadata",
                "all non-project files and directories inside the client directory",
            ],
            "recoverable": False,
            "fingerprint": self.fingerprint,
        }


class ClientNotEmptyError(ValidationError):
    """The selected client has project directories and cannot be deleted."""

    def __init__(self, project_count: int):
        super().__init__(
            f"Client contains {project_count} project director"
            f"{'y' if project_count == 1 else 'ies'}; delete all projects first."
        )
        self.project_count = project_count


class PartialDeletionError(OSError):
    """Deletion began but some of the client directory could not be removed."""

    def __init__(self, path: Path, reason: OSError):
        super().__init__(f"Client deletion began but cleanup failed at {path}: {reason}")
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


def _is_reparse_point(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _safe_directory(path: Path) -> bool:
    mode = path.lstat().st_mode
    return stat.S_ISDIR(mode) and not path.is_symlink() and not _is_reparse_point(path)


def _children(parent: Path) -> list[Path]:
    try:
        return sorted(parent.iterdir(), key=lambda child: child.name)
    except OSError as exc:
        raise ContextError(f"Unable to read client ownership directory: {parent}") from exc


def _find_client(clients: Path, client_id: str) -> tuple[Path, dict[str, object]]:
    matches: list[tuple[Path, dict[str, object]]] = []
    for entry in _children(clients):
        if entry.name.startswith(".deleting-client-"):
            continue
        if entry.is_symlink() or _is_reparse_point(entry):
            raise UnsafeOperationError(f"Unsafe directory entry in {clients}: {entry}")
        if not _safe_directory(entry):
            continue
        document_path = entry / "client.json"
        if not document_path.exists() and not document_path.is_symlink():
            continue
        document = _document(document_path, "mixing-client")
        if document.get("client_id") == client_id:
            matches.append((entry, document))
    if len(matches) > 1:
        raise ValidationError(f"Multiple mixing-client documents use ID '{client_id}'.")
    if not matches:
        raise ContextError(f"mixing-client not found for ID '{client_id}'.")
    return matches[0]


def _require_no_projects(projects: Path) -> None:
    if not projects.exists() or not _safe_directory(projects):
        raise ContextError(f"Client Projects directory is missing or unsafe: {projects}")
    project_directories = 0
    for entry in _children(projects):
        info = entry.lstat()
        if _is_reparse_point(entry) or stat.S_ISLNK(info.st_mode):
            raise UnsafeOperationError(f"Client Projects contains a symlink or junction: {entry}")
        if stat.S_ISDIR(info.st_mode):
            project_directories += 1
        elif not stat.S_ISREG(info.st_mode):
            raise UnsafeOperationError(f"Client Projects contains a special filesystem entry: {entry}")
    if project_directories:
        raise ClientNotEmptyError(project_directories)


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
            raise UnsafeOperationError(f"Client contains an unsafe directory or mount: {directory}")
        for entry in _children(directory):
            info = entry.lstat()
            if info.st_dev != device or _is_reparse_point(entry) or stat.S_ISLNK(info.st_mode):
                raise UnsafeOperationError(f"Client contains a symlink, junction, or mount: {entry}")
            if stat.S_ISDIR(info.st_mode):
                kind = "dir"
                pending.append(entry)
            elif stat.S_ISREG(info.st_mode):
                kind = "file"
                files += 1
                total_bytes += info.st_size
            else:
                raise UnsafeOperationError(f"Client contains a special filesystem entry: {entry}")
            relative = entry.relative_to(root).as_posix()
            digest.update(json.dumps([relative, kind, info.st_size, info.st_mtime_ns], ensure_ascii=False).encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest(), files, total_bytes


def plan_client_delete(workspace: Path, client_id: str) -> ClientDeletePlan:
    client_id = require_slug(client_id, label="Client ID")
    workspace = workspace.expanduser().absolute()
    if not workspace.exists() or not _safe_directory(workspace):
        raise ContextError(f"Workspace is missing or unsafe: {workspace}")
    workspace = workspace.resolve(strict=True)
    studio = _document(workspace / "Studio" / "studio.json", "mixing-studio")
    if not isinstance(studio.get("studio_id"), str):
        raise ValidationError("Workspace studio identity is invalid.")
    recorded_root = studio.get("root_path")
    try:
        owns_workspace = isinstance(recorded_root, str) and Path(recorded_root).expanduser().samefile(workspace)
    except OSError:
        owns_workspace = False
    if not owns_workspace:
        raise ValidationError("Workspace path does not match the Studio document ownership root.")
    clients = workspace / "Clients"
    if not clients.exists() or not _safe_directory(clients):
        raise ContextError(f"Workspace Clients directory is missing or unsafe: {clients}")
    client_path, client = _find_client(clients, client_id)
    _require_no_projects(client_path / "Projects")
    client_name = client.get("client_name")
    metadata = client["metadata"]
    if not isinstance(client_name, str) or not client_name:
        raise ValidationError("Client name is invalid.")
    inventory, files, total_bytes = _inventory(client_path)
    fingerprint = hashlib.sha256(json.dumps([
        str(workspace), client_id, metadata["document_id"], client_name, inventory,
    ], ensure_ascii=False).encode("utf-8")).hexdigest()
    return ClientDeletePlan(
        workspace, client_path, client_id, client_name, metadata["document_id"],
        fingerprint, files, total_bytes,
    )


def execute_client_delete(workspace: Path, client_id: str, *,
                          fingerprint: str, confirmed_name: str) -> ClientDeletePlan:
    if not fingerprint or not confirmed_name:
        raise ValidationError("Deletion requires a plan fingerprint and typed client name.")
    plan = plan_client_delete(workspace, client_id)
    if confirmed_name != plan.client_name or fingerprint != plan.fingerprint:
        raise ValidationError("Client identity or contents changed since the deletion summary. Review the client again.")
    temporary = plan.client_path.parent / f".deleting-client-{uuid.uuid4().hex}"
    if temporary.exists() or temporary.is_symlink():
        raise UnsafeOperationError(f"Deletion staging path already exists: {temporary}")
    try:
        plan.client_path.rename(temporary)
        shutil.rmtree(temporary)
    except OSError as exc:
        if temporary.exists():
            raise PartialDeletionError(temporary, exc) from exc
        raise
    return plan
