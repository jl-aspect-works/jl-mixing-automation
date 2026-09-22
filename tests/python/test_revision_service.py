from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jl_mixing.errors import UnsafeOperationError, ValidationError
from jl_mixing.project import ProjectCreateRequest, create_project
from jl_mixing.revision import RevisionCreateRequest, create_revision


def write_studio(root: Path) -> Path:
    (root / "Studio").mkdir(parents=True)
    (root / "Clients").mkdir()
    studio = {
        "metadata": {
            "schema": "mixing-studio", "schema_version": "1.1.0",
            "document_id": "11111111-1111-1111-1111-111111111111",
            "created_with": "jl-mixing 1.4.0", "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "studio_id": "test-studio", "studio_name": "Test Studio", "root_path": str(root),
        "defaults": {
            "mix_engineer": "Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
        "cli": {"change_directory_after_create": True},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    return root


def write_client(studio: Path) -> Path:
    root = studio / "Clients" / "Client"
    (root / "Projects").mkdir(parents=True)
    client = {
        "metadata": {
            "schema": "mixing-client", "schema_version": "1.1.0",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "created_with": "jl-mixing 1.4.0", "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "client_id": "client", "client_name": "Client",
        "defaults": {
            "artist": "Artist",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
    }
    (root / "client.json").write_text(json.dumps(client), encoding="utf-8")
    return root


def make_project(root: Path) -> Path:
    studio = write_studio(root)
    client = write_client(studio)
    return create_project(ProjectCreateRequest(client, "Song", change_directory=False)).project_root


class RevisionServiceTests(unittest.TestCase):
    def test_project_creation_provisions_variants_for_initial_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp))
            self.assertTrue((project / "04_Revisions" / "Revision_01" / "Variants").is_dir())

    def test_dry_run_plans_revision_two_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp))
            manifest_path = project / "00_Admin" / "project-manifest.json"
            before = manifest_path.read_text(encoding="utf-8")
            result = create_revision(RevisionCreateRequest(project, dry_run=True))
            self.assertFalse(result.created)
            self.assertEqual(result.previous_revision, 1)
            self.assertEqual(result.number, 2)
            self.assertEqual(result.description, "Revision 2")
            self.assertTrue(result.effective_cd)
            self.assertFalse(result.revision_root.exists())
            self.assertEqual(manifest_path.read_text(encoding="utf-8"), before)

    def test_create_revision_updates_manifest_notes_and_variants_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp))
            result = create_revision(RevisionCreateRequest(project, description="Vocal up 1 dB", change_directory=False))
            self.assertTrue(result.created)
            self.assertTrue((result.revision_root / "Revision_Notes.md").is_file())
            self.assertTrue((result.revision_root / "Variants").is_dir())
            self.assertIn("Vocal up 1 dB", (result.revision_root / "Revision_Notes.md").read_text(encoding="utf-8"))
            persisted = json.loads((project / "00_Admin" / "project-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["state"]["current_revision"], 2)
            self.assertEqual(persisted["revisions"][-1]["number"], 2)
            self.assertEqual(persisted["revisions"][-1]["description"], "Vocal up 1 dB")
            self.assertFalse(result.effective_cd)

    def test_approval_and_delivery_pointers_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp))
            manifest_path = project / "00_Admin" / "project-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["state"]["approved_revision"] = 1
            manifest["state"]["delivered_revision"] = 1
            manifest["revisions"][0]["approval"] = {"approved_at": "2030-01-02T12:00:00Z", "approved_by": "Client"}
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            create_revision(RevisionCreateRequest(project))
            updated = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["state"]["approved_revision"], 1)
            self.assertEqual(updated["state"]["delivered_revision"], 1)
            self.assertEqual(updated["revisions"][0]["approval"]["approved_by"], "Client")

    def test_source_files_are_copied_but_nested_directories_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = make_project(root / "studio")
            source = root / "prints"
            source.mkdir()
            (source / "Mix.wav").write_bytes(b"mix")
            (source / "Instrumental.wav").write_bytes(b"inst")
            result = create_revision(RevisionCreateRequest(project, source=source))
            self.assertEqual((result.revision_root / "Mix.wav").read_bytes(), b"mix")
            self.assertEqual((result.revision_root / "Instrumental.wav").read_bytes(), b"inst")
            self.assertTrue((result.revision_root / "Variants").is_dir())

            nested = root / "nested"
            (nested / "folder").mkdir(parents=True)
            (nested / "folder" / "Mix.wav").write_bytes(b"mix")
            with self.assertRaises(ValidationError):
                create_revision(RevisionCreateRequest(project, source=nested))
            self.assertFalse((project / "04_Revisions" / "Revision_03").exists())

    def test_revision_notes_name_collision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = make_project(root / "studio")
            source = root / "Revision_Notes.md"
            source.write_text("not allowed", encoding="utf-8")
            with self.assertRaises(ValidationError):
                create_revision(RevisionCreateRequest(project, source=source))
            self.assertFalse((project / "04_Revisions" / "Revision_02").exists())

    def test_case_insensitive_destination_collision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = make_project(Path(tmp))
            (project / "04_Revisions" / "revision_02").mkdir()
            with self.assertRaises((ValidationError, UnsafeOperationError)):
                create_revision(RevisionCreateRequest(project))


if __name__ == "__main__":
    unittest.main()
