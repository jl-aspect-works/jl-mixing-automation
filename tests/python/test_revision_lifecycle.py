from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jl_mixing.approval import RevisionApproveRequest, approve_revision, derive_project_stage
from jl_mixing.errors import ValidationError
from jl_mixing.project import ProjectCreateRequest, create_project
from jl_mixing.revision import RevisionCreateRequest, create_revision
from jl_mixing.revision_lifecycle import RevisionLifecycleRequest, set_revision_lifecycle
from jl_mixing.unapproval import RevisionUnapproveRequest, unapprove_revision


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
        "studio_id": "lifecycle-studio", "studio_name": "Lifecycle Studio", "root_path": str(root),
        "defaults": {
            "mix_engineer": "Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
        "cli": {"change_directory_after_create": False},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    client = root / "Clients" / "Lifecycle Client"
    (client / "Projects").mkdir(parents=True)
    client_doc = {
        "metadata": {
            "schema": "mixing-client", "schema_version": "1.1.0",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "created_with": "jl-mixing 1.4.0", "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "client_id": "lifecycle-client", "client_name": "Lifecycle Client",
        "defaults": {
            "artist": "Artist",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
    }
    (client / "client.json").write_text(json.dumps(client_doc), encoding="utf-8")
    return create_project(ProjectCreateRequest(client, "Lifecycle Song", change_directory=False)).project_root


class RevisionLifecycleTests(unittest.TestCase):
    def test_close_latest_recomputes_current_and_preserves_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            create_revision(RevisionCreateRequest(project, description="Second pass"))
            revision_two = project / "04_Revisions" / "Revision_02"
            before_files = sorted(path.relative_to(revision_two) for path in revision_two.rglob("*"))

            result = set_revision_lifecycle(RevisionLifecycleRequest(project, 2, "close"))
            self.assertEqual(result.current_revision, 1)
            manifest = json.loads((project / "00_Admin" / "project-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"]["current_revision"], 1)
            self.assertEqual(manifest["revisions"][1]["lifecycle"], "closed")
            self.assertEqual(before_files, sorted(path.relative_to(revision_two) for path in revision_two.rglob("*")))

            reopened = set_revision_lifecycle(RevisionLifecycleRequest(project, 2, "reopen"))
            self.assertEqual(reopened.current_revision, 2)

    def test_legacy_revision_without_lifecycle_is_open_and_migrates_on_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            manifest_path = project / "00_Admin" / "project-manifest.json"
            legacy = json.loads(manifest_path.read_text(encoding="utf-8"))
            legacy["revisions"][0].pop("lifecycle", None)
            manifest_path.write_text(json.dumps(legacy), encoding="utf-8")
            result = set_revision_lifecycle(RevisionLifecycleRequest(project, 1, "close"))
            self.assertEqual(result.current_revision, 0)
            self.assertEqual(result.manifest["revisions"][0]["lifecycle"], "closed")

    def test_new_revision_after_closed_latest_uses_next_historical_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            create_revision(RevisionCreateRequest(project, description="Second pass"))
            set_revision_lifecycle(RevisionLifecycleRequest(project, 2, "close"))
            third = create_revision(RevisionCreateRequest(project, description="Third pass"))
            self.assertEqual(third.number, 3)
            self.assertEqual(third.manifest["state"]["current_revision"], 3)
            self.assertEqual(third.manifest["revisions"][1]["lifecycle"], "closed")
            self.assertEqual(third.manifest["revisions"][2]["lifecycle"], "open")

    def test_close_later_revision_allows_earlier_delivered_state_to_be_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            create_revision(RevisionCreateRequest(project, description="Second pass"))
            manifest_path = project / "00_Admin" / "project-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            approved_at = manifest["revisions"][0]["created_at"]
            approve_revision(RevisionApproveRequest(project, revision=1, approved_at=approved_at))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["state"]["delivered_revision"] = 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            closed = set_revision_lifecycle(RevisionLifecycleRequest(project, 2, "close"))
            self.assertEqual(closed.current_revision, 1)
            self.assertEqual(derive_project_stage(closed.manifest), "Delivered")

    def test_unapprove_success_and_delivery_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            approve_revision(RevisionApproveRequest(project))
            result = unapprove_revision(RevisionUnapproveRequest(project, 1))
            self.assertTrue(result.updated)
            self.assertIsNone(result.manifest["state"]["approved_revision"])
            self.assertEqual(result.manifest["revisions"][0]["approval"], {"approved_at": None, "approved_by": None})

            approve_revision(RevisionApproveRequest(project))
            manifest_path = project / "00_Admin" / "project-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["state"]["delivered_revision"] = 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValidationError, "delivered revision"):
                unapprove_revision(RevisionUnapproveRequest(project, 1))
            unchanged = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(unchanged["state"]["approved_revision"], 1)

    def test_unapprove_nonapproved_revision_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            with self.assertRaisesRegex(ValidationError, "not the approved revision"):
                unapprove_revision(RevisionUnapproveRequest(project, 1))


if __name__ == "__main__":
    unittest.main()
