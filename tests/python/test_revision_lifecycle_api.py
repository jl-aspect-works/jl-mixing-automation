from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jl_mixing.api.revision_lifecycle import RevisionLifecycleApiRequest, execute as lifecycle_execute
from jl_mixing.api.revision_unapprove import RevisionUnapproveApiRequest, execute as unapprove_execute
from jl_mixing.approval import RevisionApproveRequest, approve_revision
from jl_mixing.project import ProjectCreateRequest, create_project
from jl_mixing.revision import RevisionCreateRequest, create_revision

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def write_project(root: Path) -> Path:
    (root / "Studio").mkdir(parents=True)
    (root / "Clients").mkdir()
    studio = {
        "metadata": {
            "schema": "mixing-studio", "schema_version": "1.1.0",
            "document_id": "11111111-1111-1111-1111-111111111111",
            "created_with": "jl-mixing 2.0.0", "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "studio_id": "lifecycle-api-studio", "studio_name": "Lifecycle API Studio", "root_path": str(root),
        "defaults": {
            "mix_engineer": "Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
        "cli": {"change_directory_after_create": False},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    client = root / "Clients" / "Lifecycle API Client"
    (client / "Projects").mkdir(parents=True)
    client_doc = {
        "metadata": {
            "schema": "mixing-client", "schema_version": "1.1.0",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "created_with": "jl-mixing 2.0.0", "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "client_id": "lifecycle-api-client", "client_name": "Lifecycle API Client",
        "defaults": {
            "artist": "Artist",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
    }
    (client / "client.json").write_text(json.dumps(client_doc), encoding="utf-8")
    return create_project(ProjectCreateRequest(client, "Lifecycle API Song", change_directory=False)).project_root


class RevisionLifecycleApiTests(unittest.TestCase):
    def test_close_and_reopen_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            create_revision(RevisionCreateRequest(project, description="Second"))
            payload, code = lifecycle_execute(RevisionLifecycleApiRequest(project, 2, "close"))
            self.assertEqual(code, 0)
            self.assertEqual(payload["operation"], "revision.close")
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["data"]["revision"]["lifecycle"], "closed")
            self.assertEqual(payload["data"]["state"]["current_revision"], 1)

            payload, code = lifecycle_execute(RevisionLifecycleApiRequest(project, 2, "reopen"))
            self.assertEqual(code, 0)
            self.assertEqual(payload["operation"], "revision.reopen")
            self.assertEqual(payload["data"]["state"]["current_revision"], 2)

    def test_dry_run_and_already_closed_are_structured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            manifest = project / "00_Admin" / "project-manifest.json"
            before = manifest.read_bytes()
            payload, code = lifecycle_execute(RevisionLifecycleApiRequest(project, 1, "close", dry_run=True))
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(before, manifest.read_bytes())
            lifecycle_execute(RevisionLifecycleApiRequest(project, 1, "close"))
            payload, code = lifecycle_execute(RevisionLifecycleApiRequest(project, 1, "close"))
            self.assertNotEqual(code, 0)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["errors"][0]["code"], "REVISION_ALREADY_CLOSED")

    def test_unapprove_success_and_delivered_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            approve_revision(RevisionApproveRequest(project))
            payload, code = unapprove_execute(RevisionUnapproveApiRequest(project, 1))
            self.assertEqual(code, 0)
            self.assertEqual(payload["operation"], "revision.unapprove")
            self.assertIsNone(payload["data"]["state"]["approved_revision"])

            approve_revision(RevisionApproveRequest(project))
            manifest_path = project / "00_Admin" / "project-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["state"]["delivered_revision"] = 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            payload, code = unapprove_execute(RevisionUnapproveApiRequest(project, 1))
            self.assertNotEqual(code, 0)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["errors"][0]["code"], "REVISION_DELIVERED")

    def test_cli_dispatches_lifecycle_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            env = os.environ.copy()
            env["PYTHONPATH"] = str(SRC)
            close = subprocess.run(
                [sys.executable, "-m", "jl_mixing.cli", "revision", "close", "--json", "--project", str(project), "--revision", "1"],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False,
            )
            self.assertEqual(close.returncode, 0, close.stderr)
            self.assertEqual(json.loads(close.stdout)["operation"], "revision.close")
            reopen = subprocess.run(
                [sys.executable, "-m", "jl_mixing.cli", "revision", "reopen", "--json", "--project", str(project), "--revision", "1"],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False,
            )
            self.assertEqual(reopen.returncode, 0, reopen.stderr)
            self.assertEqual(json.loads(reopen.stdout)["operation"], "revision.reopen")


if __name__ == "__main__":
    unittest.main()
