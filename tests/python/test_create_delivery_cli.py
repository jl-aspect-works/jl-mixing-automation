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
        "studio_id": "delivery-human-studio", "studio_name": "Delivery Human Studio", "root_path": str(root),
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
    (revision / "WORK scratch.wav").write_bytes(b"scratch")
    approve_revision(RevisionApproveRequest(project_root=project, approved_at="2030-01-01T12:01:00Z"))
    return project


def run_cli(cwd: Path, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "jl_mixing.create_delivery_cli", *args],
        cwd=cwd, env=env, text=True, capture_output=True, check=False,
    )


class CreateDeliveryCliTests(unittest.TestCase):
    def test_help_matches_human_command_surface(self) -> None:
        proc = run_cli(ROOT, "--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Usage: create-delivery", proc.stdout)
        self.assertIn("--overwrite", proc.stdout)
        self.assertIn("--clean", proc.stdout)
        self.assertIn("--zip", proc.stdout)

    def test_dry_run_lists_plan_and_writes_structured_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = write_project(root / "studio")
            result_file = root / "result.json"
            result_file.write_text("", encoding="utf-8")
            proc = run_cli(
                project, "--dry-run", "--zip",
                extra_env={"JL_MIXING_DELIVERY_RESULT_FILE": str(result_file.resolve())},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Dry run - no changes made.", proc.stdout)
            self.assertIn("Selected files:", proc.stdout)
            self.assertIn("Drum Stems.wav", proc.stdout)
            self.assertIn("WORK scratch.wav    working prefix", proc.stdout)
            self.assertIn("state.delivered_revision: null -> 1", proc.stdout)
            self.assertIn("SHA-256 verification", proc.stdout)
            payload = json.loads(result_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "planned")
            self.assertIsNone(payload["delivered_revision"])
            self.assertTrue(payload["zip_requested"])
            manifest = json.loads((project / "00_Admin" / "project-manifest.json").read_text(encoding="utf-8"))
            self.assertIsNone(manifest["state"]["delivered_revision"])

    def test_create_zip_preserves_edited_delivery_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            notes = project / "05_Final_Delivery" / "Delivery_Notes.md"
            notes.write_text("Custom client delivery note\n", encoding="utf-8")
            proc = run_cli(project, "--zip")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Final delivery created successfully.", proc.stdout)
            self.assertIn("Files delivered:     2", proc.stdout)
            self.assertIn("Project state:       Delivered", proc.stdout)
            self.assertIn("Transfer delivery-song-rev-01-", proc.stdout)
            self.assertEqual(notes.read_text(encoding="utf-8"), "Custom client delivery note\n")
            archives = list((project / "05_Final_Delivery").glob("delivery-song-rev-01-*.zip"))
            self.assertEqual(len(archives), 1)
            self.assertTrue((project / "05_Final_Delivery" / "Stems" / "Drum Stems.wav").is_file())

    def test_clean_dry_run_warns_and_lists_deletions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            delivery = project / "05_Final_Delivery"
            (delivery / "old.txt").write_text("old", encoding="utf-8")
            proc = run_cli(project, "--clean", "--dry-run")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Warning: --clean will remove every existing item inside:", proc.stdout)
            self.assertIn("Would delete from 05_Final_Delivery/:", proc.stdout)
            self.assertIn("old.txt", proc.stdout)
            self.assertTrue((delivery / "old.txt").exists())

    def test_argument_conflicts_and_removed_options_preserve_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            proc = run_cli(project, "--overwrite", "--clean")
            self.assertEqual(proc.returncode, 2)
            self.assertIn("mutually exclusive", proc.stderr)
            expectations = {
                "--revision": "always uses state.approved_revision",
                "--checksum": "SHA-256 verification is mandatory",
                "--mark-delivered": "records the delivered revision automatically",
                "--non-interactive": "does not prompt",
            }
            for option, text in expectations.items():
                proc = run_cli(project, option)
                self.assertEqual(proc.returncode, 2)
                self.assertIn(text, proc.stderr)


if __name__ == "__main__":
    unittest.main()
