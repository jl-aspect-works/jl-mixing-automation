#!/usr/bin/env python3
"""Validate and derive JL Mixing Automation v1.1 project state.

This utility intentionally performs structural checks only. Delivery hashes are
format-checked but not recalculated during routine workflow validation.
"""

from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime
import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any


class StateValidationError(ValueError):
    """Raised when a project state or corresponding filesystem is invalid."""


def parse_args():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=("records", "pointers", "directories", "delivery", "all", "derive"),
    )
    parser.add_argument("path", type=Path, help="project root or manifest, depending on mode")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StateValidationError(f"Unable to read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise StateValidationError(f"JSON document must be an object: {path}")
    return value


def parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise StateValidationError(f"{label} must be an ISO-8601 date-time")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise StateValidationError(f"{label} is invalid: {error}") from error


def validate_created_with(metadata: dict[str, Any], label: str) -> None:
    """Validate creator provenance without coupling it to schema_version."""
    value = metadata.get("created_with")
    if not isinstance(value, str) or not re.fullmatch(
        r"jl-mixing [0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?",
        value,
    ):
        raise StateValidationError(
            f"{label} created_with must identify a semantic jl-mixing release"
        )


def revision_lifecycle(revision: dict[str, Any]) -> str:
    lifecycle = revision.get("lifecycle", "open")
    if lifecycle not in ("open", "closed"):
        raise StateValidationError(
            f"Revision {revision.get('number')} lifecycle must be open or closed"
        )
    return lifecycle


def validate_records(document: dict[str, Any]) -> None:
    revisions = document.get("revisions")
    state = document.get("state")
    if not isinstance(revisions, list):
        raise StateValidationError("revisions must be an array")
    if not isinstance(state, dict):
        raise StateValidationError("state must be an object")
    if any(not isinstance(item, dict) for item in revisions):
        raise StateValidationError("every revision must be an object")

    numbers = [item.get("number") for item in revisions]
    expected = list(range(1, len(revisions) + 1))
    if numbers != expected:
        raise StateValidationError(
            f"Revision numbers must be ascending and contiguous: expected {expected}, got {numbers}"
        )

    open_numbers = [
        revision["number"]
        for revision in revisions
        if revision_lifecycle(revision) == "open"
    ]
    current = state.get("current_revision")
    expected_current = max(open_numbers, default=0)
    if current != expected_current:
        raise StateValidationError(
            f"state.current_revision must equal highest open revision {expected_current}; got {current}"
        )

    for revision in revisions:
        number = revision.get("number")
        approval = revision.get("approval")
        if not isinstance(approval, dict):
            raise StateValidationError(f"Revision {number} approval must be an object")
        approved_at = approval.get("approved_at")
        approved_by = approval.get("approved_by")
        if (approved_at is None) != (approved_by is None):
            raise StateValidationError(
                f"Revision {number} approval fields must both be null or both populated"
            )
        if approved_at is not None:
            if not isinstance(approved_by, str) or not approved_by.strip():
                raise StateValidationError(f"Revision {number} approved_by is invalid")
            created = parse_timestamp(revision.get("created_at"), f"Revision {number} created_at")
            approved = parse_timestamp(approved_at, f"Revision {number} approved_at")
            if approved < created:
                raise StateValidationError(f"Revision {number} approval predates creation")


def revision_map(document: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in document.get("revisions", []):
        if isinstance(item, dict) and isinstance(item.get("number"), int):
            result[item["number"]] = item
    return result


def validate_pointers(document: dict[str, Any]) -> None:
    revisions = revision_map(document)
    state = document.get("state", {})
    if not isinstance(state, dict):
        raise StateValidationError("state must be an object")

    for field in ("approved_revision", "delivered_revision"):
        value = state.get(field)
        if value is None:
            continue
        if value not in revisions:
            raise StateValidationError(f"state.{field} references missing Revision {value}")
        approval = revisions[value].get("approval", {})
        if not isinstance(approval, dict) or approval.get("approved_at") is None or approval.get("approved_by") is None:
            raise StateValidationError(f"state.{field} references unapproved Revision {value}")


def validate_directories(project_root: Path, document: dict[str, Any]) -> None:
    root = project_root / "04_Revisions"
    if not root.is_dir() or root.is_symlink():
        raise StateValidationError(f"Revision root is missing or unsafe: {root}")

    expected = {f"Revision_{item['number']:02d}" for item in document.get("revisions", [])}
    for name in sorted(expected):
        path = root / name
        if not path.is_dir() or path.is_symlink():
            raise StateValidationError(f"Revision directory is missing or unsafe: {path}")

    pattern = re.compile(r"^revision_[0-9]+$", re.IGNORECASE)
    for entry in root.iterdir():
        if pattern.match(entry.name) and entry.name not in expected:
            raise StateValidationError(
                f"Unrecorded or incorrectly cased revision directory: {entry}"
            )


def validate_delivery(project_root: Path, project: dict[str, Any]) -> None:
    delivery_path = project_root / "05_Final_Delivery" / "delivery-manifest.json"
    delivered = project.get("state", {}).get("delivered_revision")

    if delivered is None:
        if delivery_path.exists() or delivery_path.is_symlink():
            raise StateValidationError(
                "A delivery manifest exists while state.delivered_revision is null"
            )
        return

    if not delivery_path.is_file() or delivery_path.is_symlink():
        raise StateValidationError(
            "state.delivered_revision requires a valid delivery manifest"
        )
    delivery = load_json(delivery_path)
    metadata = delivery.get("metadata", {})
    if (
        not isinstance(metadata, dict)
        or metadata.get("schema") != "mixing-delivery"
        or metadata.get("schema_version") != "1.1.0"
    ):
        raise StateValidationError("Delivery manifest has an incompatible schema identity")
    validate_created_with(metadata, "Delivery manifest")

    revisions = revision_map(project)
    revision = revisions.get(delivered)
    if revision is None:
        raise StateValidationError(f"Delivered Revision {delivered} does not exist")

    checks = [
        (delivery.get("project", {}).get("project_document_id"), project.get("metadata", {}).get("document_id"), "project document ID"),
        (delivery.get("project", {}).get("project_id"), project.get("project_id"), "project ID"),
        (delivery.get("project", {}).get("project_name"), project.get("project_name"), "project name"),
        (delivery.get("client", {}).get("client_document_id"), project.get("client", {}).get("client_document_id"), "client document ID"),
        (delivery.get("client", {}).get("client_id"), project.get("client", {}).get("client_id"), "client ID"),
        (delivery.get("revision", {}).get("number"), delivered, "delivered revision number"),
        (delivery.get("revision", {}).get("revision_id"), revision.get("revision_id"), "revision ID"),
        (delivery.get("revision", {}).get("description"), revision.get("description"), "revision description"),
        # Approval is an immutable package-time snapshot. A later reapproval of
        # the same revision replaces the project record but must not rewrite or
        # invalidate an existing delivery manifest. Its non-null structure is
        # enforced by the delivery schema.
        (delivery.get("delivery", {}).get("method"), project.get("delivery", {}).get("method"), "delivery method"),
    ]
    for actual, expected, label in checks:
        if actual != expected:
            raise StateValidationError(
                f"Delivery manifest {label} does not match the project"
            )

    files = delivery.get("files")
    if not isinstance(files, list) or not files:
        raise StateValidationError(
            "Delivery manifest must list at least one delivered file"
        )

    seen: dict[str, str] = {}
    sha_pattern = re.compile(r"^[0-9a-f]{64}$")
    delivery_root = project_root / "05_Final_Delivery"
    for record in files:
        if not isinstance(record, dict):
            raise StateValidationError("Every delivery file record must be an object")
        relative = record.get("path")
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise StateValidationError(f"Unsafe delivery path: {relative!r}")
        segments = relative.split("/")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or any(part in ("", ".", "..") for part in segments):
            raise StateValidationError(f"Unsafe delivery path: {relative}")
        key = relative.casefold()
        if key in seen:
            raise StateValidationError(
                f"Case-insensitive delivery-path collision: {seen[key]} and {relative}"
            )
        seen[key] = relative

        destination = delivery_root.joinpath(*pure.parts)
        if not destination.is_file() or destination.is_symlink():
            raise StateValidationError(
                f"Delivered file is missing or unsafe: {destination}"
            )
        size = record.get("size_bytes")
        sha256 = record.get("sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise StateValidationError(f"Invalid size_bytes for {relative}")
        if not isinstance(sha256, str) or not sha_pattern.fullmatch(sha256):
            raise StateValidationError(f"Invalid SHA-256 format for {relative}")


def project_paths(path: Path, manifest_mode: bool = False) -> tuple[Path, Path]:
    if manifest_mode:
        manifest = path
        try:
            root = manifest.parent.parent
        except IndexError as error:
            raise StateValidationError(f"Invalid project manifest path: {manifest}") from error
    else:
        root = path
        manifest = root / "00_Admin" / "project-manifest.json"
    return root, manifest


def validate_all(project_root: Path, document: dict[str, Any]) -> None:
    metadata = document.get("metadata", {})
    if (
        not isinstance(metadata, dict)
        or metadata.get("schema") != "mixing-project"
        or metadata.get("schema_version") != "1.1.0"
    ):
        raise StateValidationError("Project manifest has an incompatible schema identity")
    validate_created_with(metadata, "Project manifest")
    validate_records(document)
    validate_pointers(document)
    validate_directories(project_root, document)
    validate_delivery(project_root, document)


def derive_stage(document: dict[str, Any]) -> str:
    state = document["state"]
    current = state["current_revision"]
    approved = state.get("approved_revision")
    delivered = state.get("delivered_revision")
    if current == 0:
        if delivered is not None:
            return "Delivered"
        if approved is not None:
            return "Approved"
        return "Setup"
    if current != approved:
        return "In progress"
    if delivered != current:
        return "Approved"
    return "Delivered"


def main() -> int:
    args = parse_args()
    try:
        if args.mode in ("records", "pointers"):
            document = load_json(args.path)
            if args.mode == "records":
                validate_records(document)
            else:
                validate_pointers(document)
            return 0

        project_root, manifest_path = project_paths(args.path)
        document = load_json(manifest_path)
        if args.mode == "directories":
            validate_directories(project_root, document)
        elif args.mode == "delivery":
            validate_delivery(project_root, document)
        else:
            validate_all(project_root, document)
            if args.mode == "derive":
                print(derive_stage(document))
        return 0
    except StateValidationError as error:
        print(error, file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
