"""Authoritative delivery reconciliation and generated-package management."""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .context import resolve_project
from .delivery import _generated_zip_pattern, _regular_no_symlink, _safe_relative, _sha256
from .errors import ContextError, UnsafeOperationError, ValidationError
from .filesystem_noise import path_contains_filesystem_noise
from .revision import _load_manifest, _validate_project_state
from .versions import application_root


@dataclass(frozen=True)
class DeliveryStatusRequest:
    project_root: Path


@dataclass(frozen=True)
class DeliveryDeletePackageRequest:
    project_root: Path
    zip_name: str


def _modified_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except OSError:
        return None


def _issue(code: str, message: str, *, path: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "message": message}
    if path is not None:
        result["path"] = path
    return result


def _delivery_manifest(path: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    if not path.exists() and not path.is_symlink():
        return None, issues
    if path.is_symlink() or not path.is_file():
        issues.append(_issue("DELIVERY_MANIFEST_UNSAFE", "Delivery manifest is not a safe regular file.", path=path.name))
        return None, issues
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(_issue("DELIVERY_MANIFEST_INVALID", f"Delivery manifest cannot be read: {exc}", path=path.name))
        return None, issues
    if not isinstance(document, dict):
        issues.append(_issue("DELIVERY_MANIFEST_INVALID", "Delivery manifest must be a JSON object.", path=path.name))
        return None, issues
    schema_path = application_root() / "schemas" / "delivery-manifest.schema.json"
    try:
        import jsonschema

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(document)
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextError(f"Required delivery schema is unreadable: {schema_path}") from exc
    except jsonschema.ValidationError as exc:
        issues.append(_issue("DELIVERY_MANIFEST_INVALID", f"Delivery manifest failed schema validation: {exc.message}", path=path.name))
        return document, issues
    return document, issues


def _root_snapshot(delivery_root: Path, project_id: str) -> tuple[dict[str, Path], list[dict[str, Any]]]:
    files: dict[str, Path] = {}
    issues: list[dict[str, Any]] = []
    generated = _generated_zip_pattern(project_id)
    try:
        paths = sorted(
            delivery_root.rglob("*"),
            key=lambda item: (item.relative_to(delivery_root).as_posix().casefold(), item.relative_to(delivery_root).as_posix()),
        )
    except OSError as exc:
        raise ContextError(f"Unable to enumerate delivery folder: {delivery_root}") from exc
    for path in paths:
        relative = path.relative_to(delivery_root).as_posix()
        if path.is_symlink():
            issues.append(_issue("UNSAFE_DELIVERY_ITEM", "Symbolic links are not allowed in managed delivery state.", path=relative))
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            issues.append(_issue("UNSAFE_DELIVERY_ITEM", "Unsupported delivery item type.", path=relative))
            continue
        if path_contains_filesystem_noise(relative):
            continue
        if path.parent == delivery_root and generated.fullmatch(path.name):
            continue
        files[relative] = path
    return files, issues


def _hash_zip_member(handle: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with handle.open(name, "r") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_record(path: Path, delivery_root: Path, snapshot: dict[str, Path]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "name": path.name,
        "path": str(path),
        "size_bytes": None,
        "modified_at": _modified_iso(path),
        "status": "invalid",
        "issues": [],
    }
    try:
        record["size_bytes"] = path.stat().st_size
    except OSError:
        pass
    if path.is_symlink() or not path.is_file():
        record["status"] = "unsafe"
        record["issues"].append(_issue("PACKAGE_UNSAFE", "Generated package path is not a safe regular file.", path=path.name))
        return record
    try:
        with zipfile.ZipFile(path, "r") as handle:
            members = {
                info.filename
                for info in handle.infolist()
                if not info.is_dir() and not path_contains_filesystem_noise(info.filename)
            }
            expected = set(snapshot)
            missing = sorted(expected - members)
            extra = sorted(members - expected)
            if missing:
                record["issues"].append(_issue("PACKAGE_MISSING_FILES", "Package is missing current delivery files: " + ", ".join(missing)))
            if extra:
                record["issues"].append(_issue("PACKAGE_EXTRA_FILES", "Package contains files not present in the current delivery folder: " + ", ".join(extra)))
            for relative in sorted(expected & members):
                current = snapshot[relative]
                try:
                    current_hash = _sha256(current)
                    packaged_hash = _hash_zip_member(handle, relative)
                except (OSError, KeyError, RuntimeError) as exc:
                    record["issues"].append(_issue("PACKAGE_VERIFY_FAILED", f"Unable to verify packaged file: {exc}", path=relative))
                    continue
                if current_hash != packaged_hash:
                    record["issues"].append(_issue("PACKAGE_STALE_FILE", "Packaged file differs from the current delivery file.", path=relative))
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        record["issues"].append(_issue("PACKAGE_INVALID", f"Package cannot be read as a ZIP archive: {exc}", path=path.name))
        return record
    record["status"] = "current" if not record["issues"] else "stale"
    return record


def inspect_delivery(request: DeliveryStatusRequest) -> dict[str, Any]:
    project_root = resolve_project(request.project_root, Path.cwd())
    project_manifest = _load_manifest(project_root)
    current_revision = _validate_project_state(project_manifest)
    project_id = project_manifest.get("project_id", "")
    delivery_root = project_root / "05_Final_Delivery"
    if delivery_root.is_symlink() or not delivery_root.is_dir():
        raise ContextError(f"Delivery root is missing or unsafe: {delivery_root}")

    delivery_manifest_path = delivery_root / "delivery-manifest.json"
    delivery_manifest, issues = _delivery_manifest(delivery_manifest_path)
    snapshot, snapshot_issues = _root_snapshot(delivery_root, str(project_id))
    issues.extend(snapshot_issues)

    state = project_manifest.get("state", {}) if isinstance(project_manifest.get("state"), dict) else {}
    approved_revision = state.get("approved_revision")
    delivered_revision = state.get("delivered_revision")
    source_revision: int | None = None
    tracked_paths: set[str] = set()
    deliverables: list[dict[str, Any]] = []

    if delivery_manifest is not None:
        manifest_project = delivery_manifest.get("project")
        if not isinstance(manifest_project, dict) or manifest_project.get("project_id") != project_id:
            issues.append(_issue("DELIVERY_PROJECT_MISMATCH", "Delivery manifest does not belong to the current project.", path="delivery-manifest.json"))
        revision = delivery_manifest.get("revision")
        if isinstance(revision, dict) and isinstance(revision.get("number"), int):
            source_revision = revision["number"]
        else:
            issues.append(_issue("DELIVERY_SOURCE_REVISION_INVALID", "Delivery manifest does not identify a valid source revision.", path="delivery-manifest.json"))
        if source_revision is not None and approved_revision != source_revision:
            issues.append(_issue("DELIVERY_SOURCE_STALE", f"Delivery was built from Revision {source_revision:02d}, but Revision {approved_revision:02d} is approved." if isinstance(approved_revision, int) else f"Delivery was built from Revision {source_revision:02d}, but there is no approved revision."))
        if source_revision is not None and delivered_revision != source_revision:
            issues.append(_issue("DELIVERED_REVISION_MISMATCH", "Project delivered-revision state does not match the delivery manifest source revision."))

        records = delivery_manifest.get("files")
        if isinstance(records, list):
            for item in records:
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    issues.append(_issue("DELIVERABLE_RECORD_INVALID", "Delivery manifest contains an invalid file record.", path="delivery-manifest.json"))
                    continue
                relative = item["path"]
                try:
                    _safe_relative(relative)
                except ValidationError:
                    deliverables.append({"path": relative, "deliverable_type": item.get("deliverable_type"), "size_bytes": None, "expected_sha256": item.get("sha256"), "actual_sha256": None, "status": "unsafe"})
                    issues.append(_issue("DELIVERABLE_PATH_UNSAFE", "Manifest-managed deliverable path is unsafe.", path=relative))
                    continue
                tracked_paths.add(relative)
                path = delivery_root.joinpath(*_safe_relative(relative).parts)
                record: dict[str, Any] = {
                    "path": relative,
                    "deliverable_type": item.get("deliverable_type"),
                    "size_bytes": None,
                    "expected_sha256": item.get("sha256"),
                    "actual_sha256": None,
                    "status": "current",
                }
                if not path.exists() and not path.is_symlink():
                    record["status"] = "missing"
                    issues.append(_issue("DELIVERABLE_MISSING", "Manifest-managed deliverable is missing.", path=relative))
                elif path.is_symlink() or not path.is_file():
                    record["status"] = "unsafe"
                    issues.append(_issue("DELIVERABLE_UNSAFE", "Manifest-managed deliverable is not a safe regular file.", path=relative))
                else:
                    try:
                        record["size_bytes"] = path.stat().st_size
                        actual = _sha256(path)
                        record["actual_sha256"] = actual
                    except OSError as exc:
                        record["status"] = "unavailable"
                        issues.append(_issue("DELIVERABLE_UNAVAILABLE", f"Unable to read manifest-managed deliverable: {exc}", path=relative))
                    else:
                        expected = item.get("sha256")
                        if not isinstance(expected, str) or actual != expected:
                            record["status"] = "mismatch"
                            issues.append(_issue("DELIVERABLE_HASH_MISMATCH", "Manifest-managed deliverable does not match its recorded SHA-256 hash.", path=relative))
                deliverables.append(record)
        else:
            issues.append(_issue("DELIVERABLE_RECORDS_INVALID", "Delivery manifest files collection is invalid.", path="delivery-manifest.json"))

    auxiliary = {"Delivery_Notes.md", "delivery-manifest.json"}
    untracked = sorted(relative for relative in snapshot if relative not in tracked_paths and relative not in auxiliary)
    for relative in untracked:
        issues.append(_issue("UNTRACKED_DELIVERY_FILE", "File is not tracked by the delivery manifest.", path=relative))

    notes_path = delivery_root / "Delivery_Notes.md"
    notes_present = _regular_no_symlink(notes_path)
    if not notes_present:
        issues.append(_issue("DELIVERY_NOTES_MISSING", "Delivery Notes are missing or unsafe.", path="Delivery_Notes.md"))
    notes = {
        "path": str(notes_path),
        "present": notes_present,
        "size_bytes": notes_path.stat().st_size if notes_present else None,
        "modified_at": _modified_iso(notes_path) if notes_present else None,
    }

    generated = _generated_zip_pattern(str(project_id))
    package_paths: list[Path] = []
    try:
        for item in delivery_root.iterdir():
            if generated.fullmatch(item.name):
                package_paths.append(item)
    except OSError as exc:
        raise ContextError(f"Unable to enumerate delivery packages: {delivery_root}") from exc
    package_paths.sort(key=lambda item: ((item.stat().st_mtime if _regular_no_symlink(item) else -1), item.name), reverse=True)
    packages = [_package_record(path, delivery_root, snapshot) for path in package_paths]
    current_packages = [item for item in packages if item["status"] == "current"]
    if not packages:
        package_state = "none"
    elif current_packages:
        package_state = "current"
    elif any(item["status"] == "unsafe" for item in packages):
        package_state = "attention"
    else:
        package_state = "stale"

    manifest_exists = delivery_manifest is not None
    readiness = "not_created" if not manifest_exists else "ready" if not issues else "needs_attention"
    return {
        "project": {"id": project_id, "name": project_manifest.get("project_name", ""), "path": str(project_root)},
        "delivery_path": str(delivery_root),
        "delivery_manifest_path": str(delivery_manifest_path),
        "state": readiness,
        "revisions": {
            "current": current_revision,
            "approved": approved_revision,
            "delivered": delivered_revision,
            "source": source_revision,
        },
        "deliverables": deliverables,
        "deliverable_count": len(deliverables),
        "untracked": untracked,
        "issues": issues,
        "notes": notes,
        "packages": packages,
        "package_state": package_state,
        "current_package": current_packages[0] if current_packages else None,
    }


def delete_generated_package(request: DeliveryDeletePackageRequest) -> dict[str, Any]:
    project_root = resolve_project(request.project_root, Path.cwd())
    project_manifest = _load_manifest(project_root)
    _validate_project_state(project_manifest)
    project_id = str(project_manifest.get("project_id", ""))
    delivery_root = project_root / "05_Final_Delivery"
    if delivery_root.is_symlink() or not delivery_root.is_dir():
        raise ContextError(f"Delivery root is missing or unsafe: {delivery_root}")
    name = request.zip_name
    if not name or Path(name).name != name or "/" in name or "\\" in name:
        raise ValidationError("Package name must be a generated ZIP filename, not a path.")
    if not _generated_zip_pattern(project_id).fullmatch(name):
        raise UnsafeOperationError("Only JL Mixing generated delivery ZIP packages may be deleted.")
    target = delivery_root / name
    if target.is_symlink():
        raise UnsafeOperationError("Generated package path is a symbolic link and will not be deleted.")
    if not target.exists():
        raise ValidationError(f"Generated package does not exist: {name}")
    if not target.is_file():
        raise UnsafeOperationError("Generated package path is not a regular file and will not be deleted.")
    try:
        target.unlink()
    except OSError as exc:
        raise ContextError(f"Unable to delete generated package: {target}") from exc
    return {
        "deleted_name": name,
        "deleted_path": str(target),
        "delivery": inspect_delivery(DeliveryStatusRequest(project_root)),
    }
