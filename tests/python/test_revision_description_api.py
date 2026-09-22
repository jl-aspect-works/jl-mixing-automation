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


def write_workspace(root: Path) -> Path:
    (root / "Studio").mkdir(parents=True)
    (root / "Clients").mkdir()
    studio = {
        "metadata": {
            "schema": "mixing-studio",
            "schema_version": "1.1.0",
            "document_id": "11111111-1111-1111-1111-111111111111",
            "created_with": "jl-mixing 1.5.0",
            "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "studio_id": "api-studio",
        "studio_name": "API Studio",
        "root_path": str(root),
        "defaults": {
            "mix_engineer": "API Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
        "cli": {"change_directory_after_create": True},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    client = root / "Clients" / "API Client"
    (client / "Projects").mkdir(parents=True)
    client_doc = {
        "metadata": {
            "schema": "mixing-client",
            "schema_version": "1.1.0",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "created_with": "jl-mixing 1.5.0",
            "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "client_id": "api-client",
        "client_name": "API Client",
        "defaults": {
            "artist": "API Artist",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
    }
    (client / "client.json").write_text(json.dumps(client_doc), encoding="utf-8")
    return create_project(
        ProjectCreateRequest(client, "API Song", change_directory=False)
    ).project_root


def run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "jl_mixing.cli", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


class RevisionDescriptionApiTests(unittest.TestCase):
    def test_updates_only_structured_description_and_preserves_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_workspace(Path(tmp))
            notes = project / "04_Revisions" / "Revision_01" / "Revision_Notes.md"
            notes_before = notes.read_text(encoding="utf-8")

            proc = run_cli(
                project,
                "revision",
                "update-description",
                "--revision",
                "1",
                "--description",
                "Brighter vocal balance",
                "--json",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["operation"], "revision.update-description")
            self.assertEqual(payload["status"], "success")
            self.assertEqual(
                payload["data"]["revision"]["description"], "Brighter vocal balance"
            )
            self.assertTrue(payload["data"]["changed"])

            manifest = json.loads(
                (project / "00_Admin" / "project-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["revisions"][0]["description"], "Brighter vocal balance")
            self.assertEqual(notes.read_text(encoding="utf-8"), notes_before)

    def test_dry_run_does_not_mutate_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_workspace(Path(tmp))
            manifest_path = project / "00_Admin" / "project-manifest.json"
            before = manifest_path.read_bytes()
            proc = run_cli(
                project,
                "revision",
                "update-description",
                "--revision",
                "1",
                "--description",
                "Dry-run description",
                "--dry-run",
                "--json",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["data"]["would_update"], [str(manifest_path.resolve())])
            self.assertEqual(manifest_path.read_bytes(), before)

    def test_nonexistent_revision_is_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_workspace(Path(tmp))
            proc = run_cli(
                project,
                "revision",
                "update-description",
                "--revision",
                "99",
                "--description",
                "Missing",
                "--json",
            )
            self.assertNotEqual(proc.returncode, 0)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["errors"][0]["code"], "REVISION_NOT_FOUND")

    def test_requires_revision_description_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_workspace(Path(tmp))
            proc = run_cli(
                project,
                "revision",
                "update-description",
                "--revision",
                "1",
                "--json",
            )
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(json.loads(proc.stdout)["errors"][0]["code"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
