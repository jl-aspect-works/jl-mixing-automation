from __future__ import annotations

import json
import os
import io
import importlib.util
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from jl_mixing.errors import UnsafeOperationError, ValidationError
from jl_mixing.managed_client_file_delete import PartialCleanupError, execute, plan
from test_managed_client_files_api import fixture


class ManagedClientFileDeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = fixture(Path(self.temp.name))
        self.original = self.project / "01_Client_Files" / "Original_Delivery"
        self.working = self.project / "02_Audio_Preparation" / "Working_Audio"
        self.provenance = self.project / "00_Admin" / "audio-prep-provenance.json"

    def record(self, source: str, working: str) -> None:
        self.provenance.write_text(json.dumps({"schema_version": 1, "entries": [{
            "source_relative_path": source, "working_relative_path": working,
        }]}), encoding="utf-8")

    def test_deletes_tracked_original_but_retains_working_copy_and_clears_lineage(self) -> None:
        folder = self.original / "Session"
        folder.mkdir()
        (folder / "Lead.wav").write_bytes(b"source")
        working = self.working / "Lead.wav"
        working.write_bytes(b"working")
        self.record("Session/Lead.wav", "02_Audio_Preparation/Working_Audio/Lead.wav")
        relative = "01_Client_Files/Original_Delivery/Session"
        summary = plan(self.project, relative)
        self.assertEqual((summary["file_count"], summary["directory_count"]), (1, 1))
        self.assertEqual(summary["working_copies_retained"], ["02_Audio_Preparation/Working_Audio/Lead.wav"])
        self.assertRaises(ValidationError, execute, self.project, relative, summary["fingerprint"], "session")
        self.assertTrue(folder.exists())
        execute(self.project, relative, summary["fingerprint"], "Session")
        self.assertFalse(folder.exists())
        self.assertEqual(working.read_bytes(), b"working")
        self.assertEqual(json.loads(self.provenance.read_text())["entries"], [])

    def test_rejects_stale_content_reserved_roots_and_symlink_escape(self) -> None:
        folder = self.original / "Session"
        folder.mkdir()
        (folder / "Lead.wav").write_bytes(b"source")
        relative = "01_Client_Files/Original_Delivery/Session"
        old = plan(self.project, relative)
        (folder / "Added.wav").write_bytes(b"new")
        self.assertRaises(ValidationError, execute, self.project, relative, old["fingerprint"], "Session")
        self.assertRaises(UnsafeOperationError, plan, self.project, "01_Client_Files/Original_Delivery")
        self.assertRaises(UnsafeOperationError, plan, self.project, "01_Client_Files/Original_Delivery/../00_Admin")
        if hasattr(os, "symlink"):
            outside = Path(self.temp.name) / "outside.txt"
            outside.write_text("keep")
            try:
                (folder / "link.txt").symlink_to(outside)
            except OSError:
                return
            self.assertRaises(UnsafeOperationError, plan, self.project, relative)
            self.assertEqual(outside.read_text(), "keep")

    def test_cleanup_failure_reports_residual_and_does_not_claim_success(self) -> None:
        folder = self.original / "Session"
        folder.mkdir()
        (folder / "Lead.wav").write_bytes(b"source")
        relative = "01_Client_Files/Original_Delivery/Session"
        summary = plan(self.project, relative)
        with patch("jl_mixing.managed_client_file_delete.shutil.rmtree", side_effect=OSError("denied")):
            with self.assertRaises(PartialCleanupError) as caught:
                execute(self.project, relative, summary["fingerprint"], "Session")
        self.assertTrue(caught.exception.path.exists())
        self.assertFalse(folder.exists())

    def test_rejects_unsafe_metadata_folder_before_deleting_source(self) -> None:
        original = self.original / "Notes.txt"
        original.write_text("keep")
        admin = self.project / "00_Admin"
        admin.rename(Path(self.temp.name) / "saved-admin")
        try:
            admin.symlink_to(Path(self.temp.name), target_is_directory=True)
        except OSError:
            self.skipTest("Directory symlinks are unavailable")
        self.assertRaises(UnsafeOperationError, plan, self.project,
                          "01_Client_Files/Original_Delivery/Notes.txt")
        self.assertEqual(original.read_text(), "keep")

    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "CLI validation dependency is unavailable")
    def test_cli_plan_and_execute_use_api_envelopes(self) -> None:
        from jl_mixing.cli import main as cli_main
        path = "01_Client_Files/Original_Delivery/Notes.txt"
        (self.original / "Notes.txt").write_text("notes")
        output = io.StringIO()
        with redirect_stdout(output):
            status = cli_main(["client-files", "delete-plan", "--json", "--project", str(self.project), "--relative-path", path])
        self.assertEqual(status, 0)
        planned = json.loads(output.getvalue())
        self.assertEqual(planned["operation"], "client.files.delete.plan")
        self.assertEqual(planned["status"], "planned")
        output = io.StringIO()
        with redirect_stdout(output):
            status = cli_main(["client-files", "delete-execute", "--json", "--project", str(self.project),
                               "--relative-path", path, "--fingerprint", planned["data"]["summary"]["fingerprint"],
                               "--confirm-name", "Notes.txt"])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "success")
        self.assertFalse((self.original / "Notes.txt").exists())


if __name__ == "__main__":
    unittest.main()
