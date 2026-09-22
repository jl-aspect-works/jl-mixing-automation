from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jl_mixing.project import ProjectCreateRequest, create_project

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


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
        "studio_id": "approval-api-studio", "studio_name": "Approval API Studio", "root_path": str(root),
        "defaults": {
            "mix_engineer": "Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
        "cli": {"change_directory_after_create": False},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    client = root / "Clients" / "Approval API Client"
    (client / "Projects").mkdir(parents=True)
    client_doc = {
        "metadata": {
            "schema": "mixing-client", "schema_version": "1.1.0",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "created_with": "jl-mixing 1.4.0", "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "client_id": "approval-api-client", "client_name": "Approval API Client",
        "defaults": {
            "artist": "Artist",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
    }
    (client / "client.json").write_text(json.dumps(client_doc), encoding="utf-8")
    return create_project(ProjectCreateRequest(client, "Approval API Song", change_directory=False)).project_root


def run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "jl_mixing.cli", *args],
        cwd=cwd, env=env, text=True, capture_output=True, check=False,
    )


class ApprovalApiTests(unittest.TestCase):
    def test_dry_run_is_structured_non_mutating_and_has_null_approved_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            manifest_path = project / "00_Admin" / "project-manifest.json"
            before = manifest_path.read_bytes()
            created = json.loads(before)["revisions"][0]["created_at"]
            proc = run_cli(
                ROOT, "revision", "approve", "--project", str(project), "--json",
                "--approved-by", "Producer", "--date", created, "--dry-run",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, "")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["operation"], "revision.approve")
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["data"]["revision"]["number"], 1)
            self.assertEqual(payload["data"]["approved_by"], "Producer")
            self.assertIsNone(payload["data"]["approved_at"])
            self.assertEqual(payload["data"]["would_update"], [str(manifest_path.resolve())])
            self.assertEqual(before, manifest_path.read_bytes())

    def test_success_updates_manifest_and_reports_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            manifest_path = project / "00_Admin" / "project-manifest.json"
            created = json.loads(manifest_path.read_text(encoding="utf-8"))["revisions"][0]["created_at"]
            proc = run_cli(
                ROOT, "revision", "approve", "--project", str(project), "--revision", "1",
                "--approved-by", "Client", "--date", created, "--json",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["data"]["project"]["id"], "approval-api-song")
            self.assertEqual(payload["data"]["approved_at"], created)
            self.assertEqual(Path(payload["data"]["revision"]["path"]), (project / "04_Revisions" / "Revision_01").resolve())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"]["approved_revision"], 1)

    def test_already_approved_revision_is_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            first = run_cli(ROOT, "revision", "approve", "--project", str(project), "--json")
            self.assertEqual(first.returncode, 0, first.stderr)
            second = run_cli(ROOT, "revision", "approve", "--project", str(project), "--json")
            self.assertEqual(second.returncode, 5)
            self.assertEqual(second.stderr, "")
            self.assertEqual(json.loads(second.stdout)["errors"][0]["code"], "REVISION_ALREADY_APPROVED")

    def test_missing_revision_and_invalid_timestamp_are_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            proc = run_cli(ROOT, "revision", "approve", "--project", str(project), "--revision", "9", "--json")
            self.assertEqual(proc.returncode, 5)
            self.assertEqual(json.loads(proc.stdout)["errors"][0]["code"], "REVISION_NOT_FOUND")
            proc = run_cli(
                ROOT, "revision", "approve", "--project", str(project),
                "--date", "2000-01-01T00:00:00Z", "--json",
            )
            self.assertEqual(proc.returncode, 5)
            self.assertEqual(json.loads(proc.stdout)["errors"][0]["code"], "INVALID_APPROVAL_TIMESTAMP")

    def test_json_mode_requires_exactly_one_project_and_json_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            cases = [
                ("revision", "approve", "--json"),
                ("revision", "approve", "--project", str(project)),
                ("revision", "approve", "--project", str(project), "--json", "--json"),
                ("revision", "approve", "--project", str(project), "--project", str(project), "--json"),
            ]
            for args in cases:
                proc = run_cli(ROOT, *args)
                self.assertEqual(proc.returncode, 2)
                self.assertEqual(proc.stderr, "")
                self.assertEqual(json.loads(proc.stdout)["errors"][0]["code"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
