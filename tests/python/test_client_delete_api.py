from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jl_mixing.api.client_delete import ClientDeleteRequest, execute, parse_args
from jl_mixing.client_delete import plan_client_delete
from jl_mixing.errors import ArgumentError
from jl_mixing.project import ProjectCreateRequest, create_project

from test_project_service import write_client, write_studio


class ClientDeleteApiTests(unittest.TestCase):
    def _setup(self, root: Path) -> tuple[Path, Path]:
        workspace = write_studio(root / "workspace")
        client = write_client(workspace)
        return workspace, client

    def test_plan_summarizes_and_permanently_deletes_non_project_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, client = self._setup(Path(tmp))
            (client / "Notes").mkdir()
            (client / "Notes" / "brief.txt").write_text("retain until confirmation", encoding="utf-8")
            result, status = execute(ClientDeleteRequest(workspace, "test-client"), plan_only=True)
            self.assertEqual(status, 0, result)
            summary = result["data"]["summary"]
            self.assertEqual(summary["client"]["name"], "Test Client")
            self.assertEqual(summary["client"]["path"], str(client.resolve()))
            self.assertEqual(summary["project_count"], 0)
            self.assertGreaterEqual(summary["file_count"], 2)
            self.assertFalse(summary["recoverable"])
            fingerprint = summary["fingerprint"]
            for confirmed in ("test client", ""):
                rejected, rejected_status = execute(
                    ClientDeleteRequest(workspace, "test-client", fingerprint, confirmed), plan_only=False)
                self.assertNotEqual(rejected_status, 0)
                self.assertEqual(rejected["status"], "blocked")
                self.assertTrue(client.exists())
            deleted, deleted_status = execute(
                ClientDeleteRequest(workspace, "test-client", fingerprint, "Test Client"), plan_only=False)
            self.assertEqual(deleted_status, 0, deleted)
            self.assertTrue(deleted["data"]["deleted"])
            self.assertFalse(deleted["data"]["recoverable"])
            self.assertFalse(client.exists())

    def test_project_directory_blocks_plan_and_stale_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, client = self._setup(Path(tmp))
            fingerprint = plan_client_delete(workspace, "test-client").fingerprint
            project = create_project(ProjectCreateRequest(client, "Created After Plan"))
            result, status = execute(
                ClientDeleteRequest(workspace, "test-client", fingerprint, "Test Client"), plan_only=False)
            self.assertNotEqual(status, 0)
            self.assertEqual(result["errors"][0]["code"], "CLIENT_NOT_EMPTY")
            self.assertEqual(result["data"]["project_count"], 1)
            self.assertTrue(client.exists())
            self.assertTrue(project.project_root.exists())

    def test_unknown_project_directory_and_duplicate_client_id_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, client = self._setup(Path(tmp))
            unknown = client / "Projects" / "Unrecognized Project"
            unknown.mkdir()
            result, status = execute(ClientDeleteRequest(workspace, "test-client"), plan_only=True)
            self.assertNotEqual(status, 0)
            self.assertEqual(result["errors"][0]["code"], "CLIENT_NOT_EMPTY")
            unknown.rmdir()
            duplicate = workspace / "Clients" / "Duplicate"
            (duplicate / "Projects").mkdir(parents=True)
            (duplicate / "client.json").write_text((client / "client.json").read_text(encoding="utf-8"), encoding="utf-8")
            result, status = execute(ClientDeleteRequest(workspace, "test-client"), plan_only=True)
            self.assertNotEqual(status, 0)
            self.assertIn("Multiple", result["errors"][0]["message"])

    def test_workspace_document_must_own_the_selected_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, client = self._setup(Path(tmp))
            studio_path = workspace / "Studio" / "studio.json"
            studio = json.loads(studio_path.read_text(encoding="utf-8"))
            studio["root_path"] = str(Path(tmp) / "different-workspace")
            studio_path.write_text(json.dumps(studio), encoding="utf-8")
            result, status = execute(ClientDeleteRequest(workspace, "test-client"), plan_only=True)
            self.assertNotEqual(status, 0)
            self.assertEqual(result["errors"][0]["code"], "VALIDATION_FAILED")
            self.assertTrue(client.exists())

    def test_changed_content_symlink_and_partial_cleanup_never_claim_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, client = self._setup(Path(tmp))
            fingerprint = plan_client_delete(workspace, "test-client").fingerprint
            (client / "new.txt").write_text("new", encoding="utf-8")
            result, status = execute(
                ClientDeleteRequest(workspace, "test-client", fingerprint, "Test Client"), plan_only=False)
            self.assertNotEqual(status, 0)
            self.assertTrue(client.exists())
            external = Path(tmp) / "external"
            external.mkdir()
            (client / "unsafe").symlink_to(external, target_is_directory=True)
            result, status = execute(ClientDeleteRequest(workspace, "test-client"), plan_only=True)
            self.assertNotEqual(status, 0)
            self.assertEqual(result["errors"][0]["code"], "UNSAFE_OPERATION")
            (client / "unsafe").unlink()
            fingerprint = plan_client_delete(workspace, "test-client").fingerprint
            with patch("jl_mixing.client_delete.shutil.rmtree", side_effect=OSError("disk offline")):
                result, status = execute(
                    ClientDeleteRequest(workspace, "test-client", fingerprint, "Test Client"), plan_only=False)
            self.assertNotEqual(status, 0)
            self.assertEqual(result["errors"][0]["code"], "PARTIAL_CLEANUP")
            self.assertTrue(Path(result["data"]["remaining_path"]).exists())
            self.assertFalse(result["data"]["deleted"])

    def test_missing_retry_and_parser_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _ = self._setup(Path(tmp))
            fingerprint = plan_client_delete(workspace, "test-client").fingerprint
            result, status = execute(
                ClientDeleteRequest(workspace, "test-client", fingerprint, "Test Client"), plan_only=False)
            self.assertEqual(status, 0, result)
            retry, retry_status = execute(
                ClientDeleteRequest(workspace, "test-client", fingerprint, "Test Client"), plan_only=False)
            self.assertNotEqual(retry_status, 0)
            self.assertEqual(retry["errors"][0]["code"], "NOT_FOUND")
        with self.assertRaises(ArgumentError):
            parse_args(["--json", "--workspace", "/tmp/studio", "--client-id", "client"], plan_only=False)
        with self.assertRaises(ArgumentError):
            parse_args(["--json", "--workspace", "/tmp/studio", "--client-id", "client", "--confirm-name", "Client"], plan_only=False)


if __name__ == "__main__":
    unittest.main()
