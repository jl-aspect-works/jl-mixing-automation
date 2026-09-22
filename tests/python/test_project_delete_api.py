from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jl_mixing.api.project_delete import ProjectDeleteRequest, execute, parse_args
from jl_mixing.errors import ArgumentError
from jl_mixing.project import ProjectCreateRequest, create_project
from jl_mixing.project_delete import plan_project_delete

from test_project_service import write_client, write_studio


class ProjectDeleteApiTests(unittest.TestCase):
    def _setup(self, root: Path) -> tuple[Path, Path, Path]:
        workspace = write_studio(root / "workspace")
        client = write_client(workspace)
        project = create_project(ProjectCreateRequest(client, "Delete Me"))
        return workspace, client, project.project_root

    def test_plan_and_execute_require_exact_name_and_fresh_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, client, project = self._setup(Path(tmp))
            external = Path(tmp) / "external-listening-copy.wav"
            external.write_bytes(b"retained")
            req = ProjectDeleteRequest(workspace, "test-client", "delete-me")
            summary, status = execute(req, plan_only=True)
            self.assertEqual(status, 0)
            self.assertEqual(summary["status"], "planned")
            self.assertEqual(summary["data"]["summary"]["project"]["path"], str(project))
            self.assertEqual(summary["data"]["external_listening_copies"], "retained")
            fingerprint = summary["data"]["summary"]["fingerprint"]
            for confirmed in ("delete me", ""):
                rejected, status = execute(ProjectDeleteRequest(workspace, "test-client", "delete-me", fingerprint, confirmed), plan_only=False)
                self.assertNotEqual(status, 0)
                self.assertEqual(rejected["status"], "blocked")
                self.assertTrue(project.exists())
            (project / "03_DAW_Project" / "session.logicx").write_bytes(b"session")
            stale, status = execute(ProjectDeleteRequest(workspace, "test-client", "delete-me", fingerprint, "Delete Me"), plan_only=False)
            self.assertNotEqual(status, 0)
            self.assertEqual(stale["status"], "blocked")
            self.assertTrue(project.exists())
            fingerprint = plan_project_delete(workspace, "test-client", "delete-me").fingerprint
            result, status = execute(ProjectDeleteRequest(workspace, "test-client", "delete-me", fingerprint, "Delete Me"), plan_only=False)
            self.assertEqual(status, 0, result)
            self.assertEqual(result["status"], "success")
            self.assertFalse(project.exists())
            self.assertTrue(client.exists())
            self.assertEqual(external.read_bytes(), b"retained")

    def test_rejects_duplicate_ids_and_mismatched_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, client, project = self._setup(Path(tmp))
            (workspace / "Clients" / ".DS_Store").write_bytes(b"metadata")
            (client / "Projects" / ".DS_Store").write_bytes(b"metadata")
            self.assertEqual(plan_project_delete(workspace, "test-client", "delete-me").project_path, project)
            manifest_path = project / "00_Admin" / "project-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["client"]["client_document_id"] = "wrong-owner"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result, status = execute(ProjectDeleteRequest(workspace, "test-client", "delete-me"), plan_only=True)
            self.assertNotEqual(status, 0)
            self.assertTrue(project.exists())
            manifest["client"]["client_document_id"] = json.loads((client / "client.json").read_text(encoding="utf-8"))["metadata"]["document_id"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            duplicate = client / "Projects" / "Second Folder" / "00_Admin"
            duplicate.mkdir(parents=True)
            (duplicate / "project-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            result, status = execute(ProjectDeleteRequest(workspace, "test-client", "delete-me"), plan_only=True)
            self.assertNotEqual(status, 0)
            self.assertIn("Multiple", result["errors"][0]["message"])

    def test_symlink_and_partial_cleanup_never_claim_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _, project = self._setup(Path(tmp))
            external = Path(tmp) / "external"
            external.mkdir()
            (external / "keep.txt").write_text("keep", encoding="utf-8")
            (project / "03_DAW_Project" / "unsafe").symlink_to(external, target_is_directory=True)
            result, status = execute(ProjectDeleteRequest(workspace, "test-client", "delete-me"), plan_only=True)
            self.assertNotEqual(status, 0)
            self.assertEqual(result["errors"][0]["code"], "UNSAFE_OPERATION")
            self.assertTrue(project.exists())
            (project / "03_DAW_Project" / "unsafe").unlink()
            fingerprint = plan_project_delete(workspace, "test-client", "delete-me").fingerprint
            with patch("jl_mixing.project_delete.shutil.rmtree", side_effect=OSError("disk offline")):
                result, status = execute(ProjectDeleteRequest(workspace, "test-client", "delete-me", fingerprint, "Delete Me"), plan_only=False)
            self.assertNotEqual(status, 0)
            self.assertEqual(result["errors"][0]["code"], "PARTIAL_CLEANUP")
            self.assertTrue(Path(result["data"]["remaining_path"]).exists())
            self.assertEqual((external / "keep.txt").read_text(encoding="utf-8"), "keep")

    def test_parser_demands_explicit_confirmation(self) -> None:
        with self.assertRaises(ArgumentError):
            parse_args(["--json", "--workspace", "/tmp/studio", "--client-id", "client", "--project-id", "song"], plan_only=False)
        with self.assertRaises(ArgumentError):
            parse_args(["--json", "--workspace", "/tmp/studio", "--client-id", "client", "--project-id", "song", "--confirm-name", "Song"], plan_only=False)


if __name__ == "__main__":
    unittest.main()
