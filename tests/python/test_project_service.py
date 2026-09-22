from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jl_mixing.errors import UnsafeOperationError, ValidationError
from jl_mixing.project import ProjectCreateRequest, create_project


def write_studio(root: Path) -> Path:
    (root / "Studio").mkdir(parents=True)
    (root / "Clients").mkdir()
    studio = {
        "metadata": {
            "schema": "mixing-studio",
            "schema_version": "1.1.0",
            "document_id": "11111111-1111-1111-1111-111111111111",
            "created_with": "jl-mixing 1.4.0",
            "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "studio_id": "test-studio",
        "studio_name": "Test Studio",
        "root_path": str(root),
        "defaults": {
            "mix_engineer": "Mix Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud transfer", "requested_deliverables": ["main_mix", "instrumental"]},
        },
        "cli": {"change_directory_after_create": True},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    return root


def write_client(studio_root: Path, *, artist: str = "Client Artist") -> Path:
    client_root = studio_root / "Clients" / "Test Client"
    (client_root / "Projects").mkdir(parents=True)
    client = {
        "metadata": {
            "schema": "mixing-client",
            "schema_version": "1.1.0",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "created_with": "jl-mixing 1.4.0",
            "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "client_id": "test-client",
        "client_name": "Test Client",
        "defaults": {
            "artist": artist,
            "audio": {"sample_rate": 96000, "bit_depth": 32, "file_format": "AIFF"},
            "delivery": {"method": "Client portal", "requested_deliverables": ["main_mix", "stems"]},
        },
    }
    (client_root / "client.json").write_text(json.dumps(client), encoding="utf-8")
    return client_root


class ProjectServiceTests(unittest.TestCase):
    def test_dry_run_inherits_defaults_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = write_studio(Path(tmp))
            client = write_client(studio)
            result = create_project(ProjectCreateRequest(client, "First Song", dry_run=True))
            self.assertFalse(result.created)
            self.assertFalse(result.project_root.exists())
            self.assertEqual(result.manifest["project_id"], "first-song")
            self.assertEqual(result.manifest["artist"], "Client Artist")
            self.assertEqual(result.manifest["mix_engineer"], "Mix Engineer")
            self.assertEqual(result.manifest["audio"], {"sample_rate": 96000, "bit_depth": 32, "file_format": "AIFF"})
            self.assertEqual(result.manifest["delivery"]["requested_deliverables"], ["main_mix", "stems"])
            self.assertTrue(result.effective_cd)
            self.assertEqual(result.manifest["state"]["current_revision"], 1)
            self.assertEqual(result.manifest["revisions"][0]["description"], "Initial mix")

    def test_create_commits_canonical_layout_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = write_studio(Path(tmp))
            client = write_client(studio)
            result = create_project(ProjectCreateRequest(
                client,
                "Second Song",
                album="Album",
                producer="Producer",
                bpm=123.5,
                musical_key="A minor",
                time_signature="4/4",
                deadline="2030-12-31",
                description="Keep the vocal intimate",
                change_directory=False,
            ))
            self.assertTrue(result.created)
            manifest_path = result.project_root / "00_Admin" / "project-manifest.json"
            snapshot_path = result.project_root / "00_Admin" / "client-profile-snapshot.json"
            self.assertTrue(manifest_path.is_file())
            self.assertTrue(snapshot_path.is_file())
            self.assertTrue((result.project_root / "01_Client_Files" / "Original_Delivery").is_dir())
            self.assertTrue((result.project_root / "03_DAW_Project").is_dir())
            self.assertTrue((result.initial_revision_root / "Revision_Notes.md").is_file())
            self.assertTrue((result.project_root / "05_Final_Delivery" / "Delivery_Notes.md").is_file())
            persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["music"]["bpm"], 123.5)
            self.assertEqual(persisted["schedule"]["deadline"], "2030-12-31")
            self.assertEqual(persisted["state"], {"current_revision": 1, "approved_revision": None, "delivered_revision": None})
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["source_client"]["client_id"], "test-client")
            self.assertNotIn("last_modified_at", snapshot["metadata"])
            self.assertFalse(result.effective_cd)

    def test_source_import_is_preflighted_and_copied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            studio = write_studio(root / "studio")
            client = write_client(studio)
            source = root / "incoming"
            (source / "Audio").mkdir(parents=True)
            (source / "Audio" / "Kick.wav").write_bytes(b"audio")
            (source / "Notes.txt").write_text("notes\n", encoding="utf-8")
            result = create_project(ProjectCreateRequest(client, "Imported Song", source=source))
            delivery = result.project_root / "01_Client_Files" / "Original_Delivery"
            self.assertEqual((delivery / "Audio" / "Kick.wav").read_bytes(), b"audio")
            self.assertEqual((delivery / "Notes.txt").read_text(encoding="utf-8"), "notes\n")
            self.assertIsNotNone(result.source_plan)

    def test_duplicate_project_id_and_case_collision_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = write_studio(Path(tmp))
            client = write_client(studio)
            create_project(ProjectCreateRequest(client, "Existing Song", project_id="stable-id"))
            with self.assertRaises(ValidationError):
                create_project(ProjectCreateRequest(client, "Different Folder", project_id="stable-id"))
            with self.assertRaises(ValidationError):
                create_project(ProjectCreateRequest(client, "existing song", project_id="different-id"))

    def test_invalid_deadline_and_unsafe_source_fail_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            studio = write_studio(root / "studio")
            client = write_client(studio)
            with self.assertRaises(ValidationError):
                create_project(ProjectCreateRequest(client, "Bad Date", deadline="2030-02-30"))
            self.assertFalse((client / "Projects" / "Bad Date").exists())
            with self.assertRaises(UnsafeOperationError):
                create_project(ProjectCreateRequest(client, "Bad Source", source=studio))
            self.assertFalse((client / "Projects" / "Bad Source").exists())

    def test_empty_client_artist_falls_back_to_client_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = write_studio(Path(tmp))
            client = write_client(studio, artist="")
            result = create_project(ProjectCreateRequest(client, "Artist Fallback", dry_run=True))
            self.assertEqual(result.manifest["artist"], "Test Client")


if __name__ == "__main__":
    unittest.main()
