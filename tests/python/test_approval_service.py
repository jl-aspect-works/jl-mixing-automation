from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jl_mixing.approval import RevisionApproveRequest, approve_revision, derive_project_stage
from jl_mixing.errors import ValidationError
from jl_mixing.project import ProjectCreateRequest, create_project
from jl_mixing.revision import RevisionCreateRequest, create_revision


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
        "studio_id": "approval-studio", "studio_name": "Approval Studio", "root_path": str(root),
        "defaults": {
            "mix_engineer": "Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
        "cli": {"change_directory_after_create": False},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    client = root / "Clients" / "Approval Client"
    (client / "Projects").mkdir(parents=True)
    client_doc = {
        "metadata": {
            "schema": "mixing-client", "schema_version": "1.1.0",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "created_with": "jl-mixing 1.4.0", "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "client_id": "approval-client", "client_name": "Approval Client",
        "defaults": {
            "artist": "Artist",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
    }
    (client / "client.json").write_text(json.dumps(client_doc), encoding="utf-8")
    return create_project(ProjectCreateRequest(client, "Approval Song", change_directory=False)).project_root


class ApprovalServiceTests(unittest.TestCase):
    def test_approve_current_revision_updates_only_approval_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            manifest_path = project / "00_Admin" / "project-manifest.json"
            before = json.loads(manifest_path.read_text(encoding="utf-8"))
            created = before["revisions"][0]["created_at"]
            result = approve_revision(RevisionApproveRequest(
                project, approved_by="Producer", approved_at=created,
            ))
            self.assertTrue(result.updated)
            self.assertEqual(result.number, 1)
            after = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(after["state"], {"current_revision": 1, "approved_revision": 1, "delivered_revision": None})
            self.assertEqual(after["revisions"][0]["approval"], {"approved_at": created, "approved_by": "Producer"})
            self.assertEqual(derive_project_stage(after), "Approved")
            self.assertEqual((project / "04_Revisions" / "Revision_01" / "Revision_Notes.md").read_text(encoding="utf-8"),
                             (project / "04_Revisions" / "Revision_01" / "Revision_Notes.md").read_text(encoding="utf-8"))

    def test_approve_older_revision_preserves_current_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            create_revision(RevisionCreateRequest(project, description="Second pass"))
            manifest = json.loads((project / "00_Admin" / "project-manifest.json").read_text(encoding="utf-8"))
            timestamp = manifest["revisions"][0]["created_at"]
            result = approve_revision(RevisionApproveRequest(project, revision=1, approved_at=timestamp))
            self.assertEqual(result.current_revision, 2)
            persisted = json.loads((project / "00_Admin" / "project-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["state"]["current_revision"], 2)
            self.assertEqual(persisted["state"]["approved_revision"], 1)
            self.assertEqual(derive_project_stage(persisted), "In progress")

    def test_dry_run_does_not_mutate_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            manifest_path = project / "00_Admin" / "project-manifest.json"
            before = manifest_path.read_bytes()
            result = approve_revision(RevisionApproveRequest(project, approved_by="Client", dry_run=True))
            self.assertFalse(result.updated)
            self.assertIsNone(result.approved_at)
            self.assertEqual(before, manifest_path.read_bytes())
            self.assertEqual(result.manifest["state"]["approved_revision"], 1)

    def test_already_approved_revision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            approve_revision(RevisionApproveRequest(project))
            with self.assertRaisesRegex(ValidationError, "already the approved revision"):
                approve_revision(RevisionApproveRequest(project))

    def test_invalid_revision_and_timestamp_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            with self.assertRaisesRegex(ValidationError, "does not exist"):
                approve_revision(RevisionApproveRequest(project, revision=9))
            manifest = json.loads((project / "00_Admin" / "project-manifest.json").read_text(encoding="utf-8"))
            created = manifest["revisions"][0]["created_at"]
            date = created[:4]
            old = f"{int(date)-1}" + created[4:]
            with self.assertRaisesRegex(ValidationError, "predates"):
                approve_revision(RevisionApproveRequest(project, approved_at=old))
            with self.assertRaisesRegex(ValidationError, "UTC offset"):
                approve_revision(RevisionApproveRequest(project, approved_at="2030-01-01T12:00:00"))


if __name__ == "__main__":
    unittest.main()
