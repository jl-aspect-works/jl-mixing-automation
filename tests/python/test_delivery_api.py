from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jl_mixing.approval import RevisionApproveRequest, approve_revision
from jl_mixing.project import ProjectCreateRequest, create_project

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def write_project(root: Path, *, approve: bool = True) -> Path:
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
            "delivery": {"method": "Portal", "requested_deliverables": ["main_mix", "stems"]},
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
            "delivery": {"method": "Portal", "requested_deliverables": ["main_mix", "stems"]},
        },
    }
    (client / "client.json").write_text(json.dumps(client_doc), encoding="utf-8")
    project = create_project(ProjectCreateRequest(client, "Delivery Song", change_directory=False)).project_root
    revision = project / "04_Revisions" / "Revision_01"
    (revision / "Delivery Song Main Mix.wav").write_bytes(b"main")
    (revision / "Drum Stems.wav").write_bytes(b"stems")
    if approve:
        approve_revision(RevisionApproveRequest(project_root=project, approved_at="2030-01-01T12:01:00Z"))
    return project


def run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "jl_mixing.cli", *args],
        cwd=cwd, env=env, text=True, capture_output=True, check=False,
    )


class DeliveryApiTests(unittest.TestCase):
    def test_dry_run_returns_planned_envelope_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            proc = run_cli(project, "delivery", "create", "--project", str(project), "--json", "--dry-run", "--zip")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, "")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["operation"], "delivery.create")
            self.assertEqual(payload["status"], "planned")
            data = payload["data"]
            self.assertEqual(data["approved_revision"], 1)
            self.assertIsNone(data["delivered_revision"])
            self.assertEqual(data["files_delivered"], 0)
            self.assertTrue(data["zip_requested"])
            self.assertTrue(data["zip_name"].endswith(".zip"))
            self.assertEqual(len(data["selected"]), 2)
            self.assertEqual(data["would_update"], [data["manifest_path"], data["delivery_path"]])
            manifest = json.loads((project / "00_Admin" / "project-manifest.json").read_text(encoding="utf-8"))
            self.assertIsNone(manifest["state"]["delivered_revision"])

    def test_success_returns_paths_and_creates_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            proc = run_cli(project, "delivery", "create", "--project", str(project), "--json", "--zip")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "success")
            data = payload["data"]
            self.assertEqual(data["delivered_revision"], 1)
            self.assertEqual(data["files_delivered"], 2)
            self.assertTrue(Path(data["delivery_manifest_path"]).is_file())
            self.assertTrue(Path(data["zip_path"]).is_file())
            self.assertTrue((project / "05_Final_Delivery" / "Stems" / "Drum Stems.wav").is_file())

    def test_second_default_delivery_requires_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            first = run_cli(project, "delivery", "create", "--project", str(project), "--json")
            self.assertEqual(first.returncode, 0, first.stderr)
            second = run_cli(project, "delivery", "create", "--project", str(project), "--json")
            self.assertEqual(second.returncode, 5)
            payload = json.loads(second.stdout)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["errors"][0]["code"], "DELIVERY_REPLACEMENT_REQUIRED")

    def test_unapproved_project_is_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp), approve=False)
            proc = run_cli(project, "delivery", "create", "--project", str(project), "--json")
            self.assertEqual(proc.returncode, 5)
            self.assertEqual(json.loads(proc.stdout)["errors"][0]["code"], "REVISION_NOT_APPROVED")

    def test_json_mode_and_replacement_argument_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            cases = (
                ("delivery", "create", "--project", str(project)),
                ("delivery", "create", "--json"),
                ("delivery", "create", "--project", str(project), "--json", "--overwrite", "--clean"),
                ("delivery", "create", "--project", str(project), "--json", "--include", ""),
            )
            for args in cases:
                proc = run_cli(project, *args)
                self.assertEqual(proc.returncode, 2)
                self.assertEqual(json.loads(proc.stdout)["errors"][0]["code"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
