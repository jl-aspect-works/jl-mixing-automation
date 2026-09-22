from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jl_mixing.client import ClientCreateRequest, create_client
from jl_mixing.errors import ValidationError


def write_studio(root: Path, *, default_cd: bool = False) -> Path:
    (root / "Studio").mkdir(parents=True)
    (root / "Clients").mkdir()
    studio = {
        "metadata": {
            "schema": "mixing-studio",
            "schema_version": "1.1.0",
            "document_id": "33333333-3333-3333-3333-333333333333",
            "created_with": "jl-mixing 1.4.0",
            "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "studio_id": "test-studio",
        "studio_name": "Test Studio",
        "root_path": str(root),
        "defaults": {
            "mix_engineer": "Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {
                "method": "Cloud transfer",
                "requested_deliverables": ["main_mix", "instrumental"],
            },
        },
        "cli": {"change_directory_after_create": default_cd},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    return root


class ClientServiceTests(unittest.TestCase):
    def test_dry_run_inherits_defaults_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = write_studio(Path(tmp), default_cd=True)
            result = create_client(ClientCreateRequest(studio, "blue-sky", dry_run=True))
            self.assertFalse(result.created)
            self.assertTrue(result.effective_cd)
            self.assertEqual(result.client_root.name, "Blue Sky")
            self.assertFalse(result.client_root.exists())
            self.assertEqual(result.client_document["client_name"], "Blue Sky")
            self.assertEqual(result.client_document["defaults"]["audio"], {
                "sample_rate": 48000,
                "bit_depth": 24,
                "file_format": "WAV",
            })
            self.assertEqual(
                result.client_document["defaults"]["delivery"]["requested_deliverables"],
                ["main_mix", "instrumental"],
            )

    def test_create_commits_client_and_projects_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = write_studio(Path(tmp))
            result = create_client(ClientCreateRequest(
                studio,
                "artist-one",
                client_name="Artist One LLC",
                artist="Artist One",
                sample_rate=96000,
                bit_depth=32,
                file_format="aiff",
                delivery_method="Drive",
                deliverables=["main_mix", "stems", "master"],
            ))
            self.assertTrue(result.created)
            self.assertTrue((result.client_root / "Projects").is_dir())
            client_file = result.client_root / "client.json"
            persisted = json.loads(client_file.read_text(encoding="utf-8"))
            self.assertEqual(persisted["client_id"], "artist-one")
            self.assertEqual(persisted["defaults"]["artist"], "Artist One")
            self.assertEqual(persisted["defaults"]["audio"]["sample_rate"], 96000)
            self.assertEqual(persisted["defaults"]["audio"]["file_format"], "AIFF")
            self.assertEqual(persisted["defaults"]["delivery"]["requested_deliverables"], ["main_mix", "stems", "master"])
            self.assertEqual(persisted["metadata"]["schema_version"], "1.1.0")
            self.assertTrue(persisted["metadata"]["created_with"].startswith("jl-mixing "))

    def test_duplicate_client_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = write_studio(Path(tmp))
            create_client(ClientCreateRequest(studio, "same-client"))
            with self.assertRaisesRegex(ValidationError, "Client ID already exists"):
                create_client(ClientCreateRequest(studio, "same-client", client_name="Different Folder"))

    def test_case_insensitive_folder_collision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = write_studio(Path(tmp))
            existing = studio / "Clients" / "Case Name"
            existing.mkdir()
            with self.assertRaisesRegex(ValidationError, "Case-insensitive path collision"):
                create_client(ClientCreateRequest(studio, "case-client", client_name="case name"))

    def test_windows_reserved_folder_name_is_rejected_on_every_platform(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = write_studio(Path(tmp))
            with self.assertRaisesRegex(ValidationError, "Reserved folder name"):
                create_client(ClientCreateRequest(studio, "reserved-client", client_name="CON"))


if __name__ == "__main__":
    unittest.main()
