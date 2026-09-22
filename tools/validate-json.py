#!/usr/bin/env python3
"""Validate canonical v1.1 examples and rejection fixtures.

The tool validates local Draft 2020-12 schemas only. Basic development mode
may skip semantic validation when ``jsonschema`` is unavailable; strict/CI
mode treats that missing dependency as a failure.
"""

from argparse import ArgumentParser
import json
from pathlib import Path
import sys
from typing import Iterable

ValidationPair = tuple[Path, Path]


def parser() -> ArgumentParser:
    result = ArgumentParser(
        description="Validate JL Mixing JSON examples or one explicit document."
    )
    result.add_argument("--schema", type=Path, action="append")
    result.add_argument("--document", type=Path, action="append")
    result.add_argument(
        "--strict",
        action="store_true",
        help="fail instead of skipping when jsonschema is unavailable",
    )
    return result


def default_pairs(root: Path) -> list[ValidationPair]:
    """Return the five canonical v1.1 schema/example pairs."""

    return [
        (root / "schemas/studio.schema.json", root / "examples/studio.json"),
        (root / "schemas/client.schema.json", root / "examples/client.json"),
        (
            root / "schemas/client-profile-snapshot.schema.json",
            root / "examples/client-profile-snapshot.json",
        ),
        (
            root / "schemas/project-manifest.schema.json",
            root / "examples/project-manifest.json",
        ),
        (
            root / "schemas/delivery-manifest.schema.json",
            root / "examples/delivery-manifest.json",
        ),
    ]


def negative_pairs(root: Path) -> list[ValidationPair]:
    """Return fixtures that each add one forbidden v1.0-era field."""

    return [
        (root / "schemas/studio.schema.json", root / "tests/fixtures/invalid-studio.json"),
        (root / "schemas/client.schema.json", root / "tests/fixtures/invalid-client.json"),
        (
            root / "schemas/client-profile-snapshot.schema.json",
            root / "tests/fixtures/invalid-client-profile-snapshot.json",
        ),
        (
            root / "schemas/project-manifest.schema.json",
            root / "tests/fixtures/invalid-project-manifest.json",
        ),
        (
            root / "schemas/delivery-manifest.schema.json",
            root / "tests/fixtures/invalid-delivery-manifest.json",
        ),
        (
            root / "schemas/studio.schema.json",
            root / "tests/fixtures/invalid-studio-duplicate-deliverables.json",
        ),
        (
            root / "schemas/project-manifest.schema.json",
            root / "tests/fixtures/invalid-project-approval-pair.json",
        ),
        (
            root / "schemas/project-manifest.schema.json",
            root / "tests/fixtures/invalid-project-empty-artist.json",
        ),
        (
            root / "schemas/project-manifest.schema.json",
            root / "tests/fixtures/invalid-project-deadline.json",
        ),
        (
            root / "schemas/delivery-manifest.schema.json",
            root / "tests/fixtures/invalid-delivery-path.json",
        ),
        (
            root / "schemas/delivery-manifest.schema.json",
            root / "tests/fixtures/invalid-delivery-uppercase-hash.json",
        ),
    ]


def validator_for(schema_path: Path):
    from jsonschema import Draft202012Validator, FormatChecker

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_pairs(pairs: Iterable[ValidationPair]) -> bool:
    failed = False
    for schema_path, document_path in pairs:
        validator = validator_for(schema_path)
        document = json.loads(document_path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
        if errors:
            failed = True
            for error in errors:
                location = ".".join(str(item) for item in error.absolute_path) or "<root>"
                print(
                    f"[FAIL] {document_path.name} at {location}: {error.message}",
                    file=sys.stderr,
                )
        else:
            print(f"[OK] Schema: {document_path.name}")
    return not failed


def validate_rejections(pairs: Iterable[ValidationPair]) -> bool:
    failed = False
    for schema_path, document_path in pairs:
        validator = validator_for(schema_path)
        document = json.loads(document_path.read_text(encoding="utf-8"))
        errors = list(validator.iter_errors(document))
        if not errors:
            failed = True
            print(
                f"[FAIL] Rejection fixture unexpectedly passed: {document_path.name}",
                file=sys.stderr,
            )
        else:
            print(f"[OK] Rejected invalid fixture: {document_path.name}")
    return not failed


def main() -> int:
    args = parser().parse_args()
    root = Path(__file__).resolve().parent.parent
    schemas = args.schema or []
    documents = args.document or []
    if len(schemas) != len(documents):
        print("--schema and --document must be supplied in matching pairs.", file=sys.stderr)
        return 2

    try:
        import jsonschema  # noqa: F401
    except ModuleNotFoundError:
        message = "Python package 'jsonschema' is not installed."
        if args.strict:
            print(f"[FAIL] JSON Schema validation: {message}", file=sys.stderr)
            return 1
        print(f"[SKIP] JSON Schema semantic validation: {message}")
        print(
            "       Optional developer setup: python3 -m venv .venv && "
            ".venv/bin/pip install -r packaging/requirements.txt"
        )
        return 0

    if schemas:
        return 0 if validate_pairs(zip(schemas, documents)) else 1

    positive_ok = validate_pairs(default_pairs(root))
    negative_ok = validate_rejections(negative_pairs(root))
    return 0 if positive_ok and negative_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
