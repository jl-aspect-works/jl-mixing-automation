#!/usr/bin/env bash
set -eu

# Purpose: Verify the scope-frozen v1.1 schema, example, and Markdown artifacts.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"

python3 - "$ROOT" <<'PY'
from pathlib import Path
import json
import re
import sys

root = Path(sys.argv[1])
schema_names = [
    "studio.schema.json",
    "client.schema.json",
    "client-profile-snapshot.schema.json",
    "project-manifest.schema.json",
    "delivery-manifest.schema.json",
]
example_names = [
    "studio.json",
    "client.json",
    "client-profile-snapshot.json",
    "project-manifest.json",
    "delivery-manifest.json",
]
expected_identities = {
    "studio.json": "mixing-studio",
    "client.json": "mixing-client",
    "client-profile-snapshot.json": "mixing-client-profile-snapshot",
    "project-manifest.json": "mixing-project",
    "delivery-manifest.json": "mixing-delivery",
}
created_with_pattern = (
    r"^jl-mixing [0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


def visit_objects(node, location="<root>"):
    if isinstance(node, dict):
        if node.get("type") == "object" and node.get("additionalProperties") is not False:
            raise AssertionError(f"object schema is not strict at {location}")
        for key, value in node.items():
            visit_objects(value, f"{location}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            visit_objects(value, f"{location}[{index}]")


for name in schema_names:
    path = root / "schemas" / name
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    metadata = schema["properties"]["metadata"]
    assert metadata["properties"]["schema_version"]["const"] == "1.1.0"
    assert metadata["properties"]["created_with"]["pattern"] == created_with_pattern
    assert "created_by" not in metadata["properties"]
    visit_objects(schema, name)

for name in example_names:
    path = root / "examples" / name
    document = json.loads(path.read_text(encoding="utf-8"))
    metadata = document["metadata"]
    assert metadata["schema"] == expected_identities[name]
    assert metadata["schema_version"] == "1.1.0"
    assert re.fullmatch(
        r"jl-mixing [0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?",
        metadata["created_with"],
    )
    assert "created_by" not in metadata

expected_templates = {
    "Intake_Report.md": (
        "# Intake Report\n\n"
        "<!-- BEGIN AUTOMATED SECTION -->\n"
        "No intake validation has been run.\n"
        "<!-- END AUTOMATED SECTION -->\n"
    ),
    "Project_Notes.md": "# Project Notes\n",
    "Preparation_Report.md": "# Preparation Report\n",
    "Revision_Notes.md": (
        "# Revision {{REVISION_NUMBER}} Notes\n\n"
        "Description: {{REVISION_DESCRIPTION}}\n"
    ),
    "Delivery_Notes.md": "# Delivery Notes\n",
    "Recall_Sheet.md": "# Recall Sheet\n",
}
for name, expected in expected_templates.items():
    actual = (root / "templates" / name).read_text(encoding="utf-8")
    assert actual == expected, f"unexpected canonical template content: {name}"

actual_markdown = {path.name for path in (root / "templates").glob("*.md") if path.name != "README.md"}
assert actual_markdown == set(expected_templates), "unexpected canonical Markdown template set"
assert not (root / "templates/project").exists()
assert not (root / "templates/revision").exists()
assert not (root / "templates/delivery").exists()
assert not (root / "schemas/legacy").exists()

print("[OK] v1.1 schema and template artifacts")
PY
pass "canonical v1.1 artifacts are strict and complete"

echo "[OK] v1.1 artifacts ($TEST_COUNT assertions)"
