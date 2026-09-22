from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jl_mixing.errors import ValidationError
from jl_mixing.metadata import create_v11, touch_document, validate_created_with, validate_v11, write_json_document


class MetadataTests(unittest.TestCase):
    def test_mutable_v11_shape_matches_contract(self) -> None:
        metadata = create_v11(
            "mixing-project",
            mutability="mutable",
            document_id="11111111-1111-1111-1111-111111111111",
            timestamp="2030-01-01T12:00:00Z",
        )
        self.assertEqual(metadata["schema_version"], "1.1.0")
        self.assertEqual(metadata["created_at"], "2030-01-01T12:00:00Z")
        self.assertEqual(metadata["last_modified_at"], metadata["created_at"])
        self.assertTrue(metadata["created_with"].startswith("jl-mixing "))
        self.assertNotIn("created_by", metadata)
        validate_v11(metadata, "mixing-project", mutability="mutable")

    def test_immutable_v11_omits_last_modified(self) -> None:
        metadata = create_v11(
            "mixing-delivery",
            mutability="immutable",
            document_id="22222222-2222-2222-2222-222222222222",
            timestamp="2030-01-01T12:00:00Z",
        )
        self.assertNotIn("last_modified_at", metadata)
        validate_v11(metadata, "mixing-delivery", mutability="immutable")

    def test_created_with_accepts_prerelease_and_build(self) -> None:
        self.assertEqual(
            validate_created_with("jl-mixing 1.5.0-rc.1+build.7"),
            "jl-mixing 1.5.0-rc.1+build.7",
        )
        for invalid in ("1.5.0", "jl-mixing 1.5", "other 1.5.0"):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                validate_created_with(invalid)

    def test_touch_changes_only_last_modified_timestamp(self) -> None:
        document = {
            "metadata": create_v11(
                "mixing-client",
                mutability="mutable",
                document_id="33333333-3333-3333-3333-333333333333",
                timestamp="2030-01-01T12:00:00Z",
            ),
            "name": "Client",
        }
        updated = touch_document(document, "2030-01-02T12:00:00Z")
        self.assertEqual(document["metadata"]["last_modified_at"], "2030-01-01T12:00:00Z")
        self.assertEqual(updated["metadata"]["last_modified_at"], "2030-01-02T12:00:00Z")
        for field in ("schema", "schema_version", "document_id", "created_with", "created_at"):
            self.assertEqual(updated["metadata"][field], document["metadata"][field])

    def test_atomic_json_write_is_utf8_and_newline_terminated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            document = {"metadata": {"schema": "test"}, "name": "Beyoncé"}
            write_json_document(path, document)
            raw = path.read_bytes()
            self.assertTrue(raw.endswith(b"\n"))
            self.assertEqual(json.loads(raw.decode("utf-8")), document)


if __name__ == "__main__":
    unittest.main()
