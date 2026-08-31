from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from jl_mixing.approval import RevisionApproveRequest, approve_revision
from jl_mixing.delivery import DeliveryCreateRequest, create_delivery
from jl_mixing.errors import ValidationError
from jl_mixing.project import ProjectCreateRequest, create_project


def write_project(root: Path) -> Path:
    (root / "Studio").mkdir(parents=True)
    (root / "Clients").mkdir()
    studio = {
        "metadata": {
            "schema": "mixing-studio", "schema_version": "1.1.0",
            "document_id": "11111111-1111-1111-1111-111111111111",
            "created_with": "jl-mixing 1.4.0", "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "studio_id": "delivery-studio", "studio_name": "Delivery Studio", "root_path": str(root),
        "defaults": {
            "mix_engineer": "Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Client portal", "requested_deliverables": ["main_mix", "instrumental", "stems"]},
        },
        "cli": {"change_directory_after_create": False},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    client = root / "Clients" / "Delivery Client"
    (client / "Projects").mkdir(parents=True)
    client_doc = {
        "metadata": {
            "schema": "mixing-client", "schema_version": "1.1.0",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "created_with": "jl-mixing 1.4.0", "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "client_id": "delivery-client", "client_name": "Delivery Client",
        "defaults": {
            "artist": "Artist",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Client portal", "requested_deliverables": ["main_mix", "instrumental", "stems"]},
        },
    }
    (client / "client.json").write_text(json.dumps(client_doc), encoding="utf-8")
    project = create_project(ProjectCreateRequest(client, "Delivery Song", change_directory=False)).project_root
    revision = project / "04_Revisions" / "Revision_01"
    (revision / "Delivery Song Main Mix.wav").write_bytes(b"main")
    (revision / "Delivery Song Instrumental.wav").write_bytes(b"instrumental")
    (revision / "Drum Stems.wav").write_bytes(b"stems")
    (revision / "WORK rough.wav").write_bytes(b"work")
    approve_revision(RevisionApproveRequest(project))
    return project


class DeliveryServiceTests(unittest.TestCase):
    def test_dry_run_plans_files_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            delivery = project / "05_Final_Delivery"
            manifest_path = project / "00_Admin" / "project-manifest.json"
            before_manifest = manifest_path.read_bytes()
            before_listing = sorted(path.relative_to(delivery).as_posix() for path in delivery.rglob("*"))
            result = create_delivery(DeliveryCreateRequest(project, dry_run=True))
            self.assertFalse(result.created)
            self.assertEqual(result.files_delivered, 0)
            self.assertEqual([record.path for record in result.plan.selected], [
                "Delivery Song Main Mix.wav",
                "Delivery Song Instrumental.wav",
                "Stems/Drum Stems.wav",
            ])
            reasons = {item.name: item.reason for item in result.plan.excluded}
            self.assertEqual(reasons["Revision_Notes.md"], "revision notes")
            self.assertEqual(reasons["Variants"], "revision variants")
            self.assertEqual(reasons["WORK rough.wav"], "working prefix")
            self.assertEqual(before_manifest, manifest_path.read_bytes())
            self.assertEqual(before_listing, sorted(path.relative_to(delivery).as_posix() for path in delivery.rglob("*")))

    def test_variants_are_excluded_but_other_subdirectories_remain_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            revision = project / "04_Revisions" / "Revision_01"
            (revision / "Variants" / "Delivery Song Instrumental Alt.wav").write_bytes(b"variant")
            result = create_delivery(DeliveryCreateRequest(project, dry_run=True))
            self.assertNotIn(
                "Delivery Song Instrumental Alt.wav",
                [record.name for record in result.plan.selected],
            )
            (revision / "Unexpected").mkdir()
            with self.assertRaisesRegex(ValidationError, "Subdirectories are not allowed"):
                create_delivery(DeliveryCreateRequest(project, dry_run=True))

    def test_create_copies_verifies_and_records_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            delivery = project / "05_Final_Delivery"
            notes = delivery / "Delivery_Notes.md"
            notes.write_text("Client-specific delivery note\n", encoding="utf-8")
            result = create_delivery(DeliveryCreateRequest(project))
            self.assertTrue(result.created)
            self.assertEqual(result.files_delivered, 3)
            self.assertEqual(result.project_stage, "Delivered")
            self.assertEqual(notes.read_text(encoding="utf-8"), "Client-specific delivery note\n")
            self.assertEqual((delivery / "Delivery Song Main Mix.wav").read_bytes(), b"main")
            self.assertEqual((delivery / "Stems" / "Drum Stems.wav").read_bytes(), b"stems")
            package = json.loads((delivery / "delivery-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(package["revision"]["number"], 1)
            self.assertEqual(len(package["files"]), 3)
            self.assertTrue(all(len(record["sha256"]) == 64 for record in package["files"]))
            manifest = json.loads((project / "00_Admin" / "project-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"]["delivered_revision"], 1)

    def test_overwrite_replaces_managed_path_set_and_preserves_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            delivery = project / "05_Final_Delivery"
            create_delivery(DeliveryCreateRequest(project))
            notes = delivery / "Delivery_Notes.md"
            notes.write_text("Edited after first package\n", encoding="utf-8")
            (delivery / "client-reference.pdf").write_bytes(b"untracked reference")
            revision = project / "04_Revisions" / "Revision_01"
            old_main = revision / "Delivery Song Main Mix.wav"
            old_main.unlink()
            (revision / "Delivery Song Main v2.wav").write_bytes(b"main-v2")
            (revision / "Delivery Song Instrumental.wav").unlink()

            result = create_delivery(DeliveryCreateRequest(project, overwrite=True))

            self.assertTrue(result.created)
            self.assertFalse((delivery / "Delivery Song Main Mix.wav").exists())
            self.assertFalse((delivery / "Delivery Song Instrumental.wav").exists())
            self.assertEqual((delivery / "Delivery Song Main v2.wav").read_bytes(), b"main-v2")
            self.assertEqual(notes.read_text(encoding="utf-8"), "Edited after first package\n")
            self.assertEqual((delivery / "client-reference.pdf").read_bytes(), b"untracked reference")
            manifest = json.loads((delivery / "delivery-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                {item["path"] for item in manifest["files"]},
                {"Delivery Song Main v2.wav", "Stems/Drum Stems.wav"},
            )

    def test_overwrite_rejects_new_path_that_collides_with_untracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            delivery = project / "05_Final_Delivery"
            create_delivery(DeliveryCreateRequest(project))
            revision = project / "04_Revisions" / "Revision_01"
            (delivery / "Custom Mix.wav").write_bytes(b"untracked")
            (revision / "Delivery Song Main Mix.wav").unlink()
            (revision / "Custom Mix.wav").write_bytes(b"new managed")

            with self.assertRaisesRegex(ValidationError, "untracked item"):
                create_delivery(DeliveryCreateRequest(project, overwrite=True))
            self.assertEqual((delivery / "Custom Mix.wav").read_bytes(), b"untracked")

    def test_clean_allows_new_path_set_and_resets_delivery_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            delivery = project / "05_Final_Delivery"
            create_delivery(DeliveryCreateRequest(project))
            (delivery / "Untracked.txt").write_text("old\n", encoding="utf-8")
            (delivery / "Delivery_Notes.md").write_text("old notes\n", encoding="utf-8")
            revision = project / "04_Revisions" / "Revision_01"
            (revision / "Delivery Song Instrumental.wav").unlink()
            result = create_delivery(DeliveryCreateRequest(project, clean=True))
            self.assertTrue(result.created)
            self.assertIn("Untracked.txt", result.plan.deletions)
            self.assertFalse((delivery / "Untracked.txt").exists())
            self.assertFalse((delivery / "Delivery Song Instrumental.wav").exists())
            self.assertNotEqual((delivery / "Delivery_Notes.md").read_text(encoding="utf-8"), "old notes\n")

    def test_zip_is_created_without_nesting_generated_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            delivery = project / "05_Final_Delivery"
            historical = delivery / "delivery-song-rev-01-20000101000000.zip"
            historical.write_bytes(b"old zip")
            result = create_delivery(DeliveryCreateRequest(project, make_zip=True))
            self.assertIsNotNone(result.zip_name)
            archive = delivery / str(result.zip_name)
            self.assertTrue(archive.is_file())
            with zipfile.ZipFile(archive) as handle:
                names = set(handle.namelist())
            self.assertIn("delivery-manifest.json", names)
            self.assertIn("Delivery Song Main Mix.wav", names)
            self.assertIn("Stems/Drum Stems.wav", names)
            self.assertNotIn(historical.name, names)
            self.assertNotIn(archive.name, names)
            self.assertTrue(historical.is_file())

    def test_filters_and_validation_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            result = create_delivery(DeliveryCreateRequest(project, include=("*Main Mix.wav",), dry_run=True))
            self.assertEqual([record.name for record in result.plan.selected], ["Delivery Song Main Mix.wav"])
            with self.assertRaisesRegex(ValidationError, "mutually exclusive"):
                create_delivery(DeliveryCreateRequest(project, overwrite=True, clean=True, dry_run=True))
            with self.assertRaisesRegex(ValidationError, "working-prefix"):
                create_delivery(DeliveryCreateRequest(project, working_prefix="", dry_run=True))

    def test_delivery_requires_approved_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            manifest_path = project / "00_Admin" / "project-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["state"]["approved_revision"] = None
            manifest["revisions"][0]["approval"] = {"approved_at": None, "approved_by": None}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "must be approved"):
                create_delivery(DeliveryCreateRequest(project, dry_run=True))


if __name__ == "__main__":
    unittest.main()
