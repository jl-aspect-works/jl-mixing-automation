from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
            "created_with": "jl-mixing 1.4.0", "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "studio_id": "approve-human-studio", "studio_name": "Approve Human Studio", "root_path": str(root),
        "defaults": {
            "mix_engineer": "Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
        "cli": {"change_directory_after_create": False},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    client = root / "Clients" / "Approve Human Client"
    (client / "Projects").mkdir(parents=True)
    client_doc = {
        "metadata": {
            "schema": "mixing-client", "schema_version": "1.1.0",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "created_with": "jl-mixing 1.4.0", "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "client_id": "approve-human-client", "client_name": "Approve Human Client",
        "defaults": {
            "artist": "Artist",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
    }
    (client / "client.json").write_text(json.dumps(client_doc), encoding="utf-8")
    return create_project(ProjectCreateRequest(client, "Approve Human Song", change_directory=False)).project_root


def run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "jl_mixing.approve_mix_cli", *args],
        cwd=cwd, env=env, text=True, capture_output=True, check=False,
    )


class ApproveMixCliTests(unittest.TestCase):
    def test_help_matches_human_command_surface(self) -> None:
        proc = run_cli(ROOT, "--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Usage: approve-mix", proc.stdout)
        self.assertIn("--approved-by NAME", proc.stdout)
        self.assertIn("--date TIMESTAMP", proc.stdout)

    def test_dry_run_reports_planned_state_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            manifest_path = project / "00_Admin" / "project-manifest.json"
            before = manifest_path.read_bytes()
            created = json.loads(before)["revisions"][0]["created_at"]
            proc = run_cli(project, "--approved-by", "Producer", "--date", created, "--dry-run")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Dry run — no changes made.", proc.stdout)
            self.assertIn("Selected revision:           1", proc.stdout)
            self.assertIn("Current approved revision:   <none>", proc.stdout)
            self.assertIn("Approver:                    Producer", proc.stdout)
            self.assertIn(f"Approval timestamp:          {created}", proc.stdout)
            arrow = "->" if os.name == "nt" else "→"
            self.assertIn(f"state.approved_revision: null {arrow} 1", proc.stdout)
            self.assertIn("state.delivered_revision: null", proc.stdout)
            self.assertEqual(before, manifest_path.read_bytes())

    def test_success_defaults_to_current_revision_and_reports_approved_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            proc = run_cli(project, "--approved-by", "Client")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Revision approved successfully.", proc.stdout)
            self.assertIn("Approved revision:           1", proc.stdout)
            self.assertIn("Approved by:                 Client", proc.stdout)
            self.assertIn("Project state:               Approved", proc.stdout)
            self.assertIn("Next:\n  create-delivery", proc.stdout)
            manifest = json.loads((project / "00_Admin" / "project-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"]["approved_revision"], 1)

    def test_approving_older_revision_warns_and_preserves_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            create_revision(RevisionCreateRequest(project, description="Second pass"))
            manifest_path = project / "00_Admin" / "project-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            created = manifest["revisions"][0]["created_at"]
            proc = run_cli(project, "--revision", "1", "--date", created)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Approved revision:           1", proc.stdout)
            self.assertIn("Current revision:            2", proc.stdout)
            self.assertIn("Project state:               In progress", proc.stdout)
            self.assertIn("approved revision is older than the current working revision", proc.stdout)
            persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["state"]["current_revision"], 2)
            self.assertEqual(persisted["state"]["approved_revision"], 1)

    def test_already_approved_revision_keeps_guidance_and_exit_five(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            first = run_cli(project)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = run_cli(project)
            self.assertEqual(second.returncode, 5)
            self.assertIn("already the approved revision", second.stderr)
            self.assertIn("No changes made.", second.stdout)
            self.assertIn("Next:\n  create-delivery", second.stdout)

    def test_removed_options_and_invalid_timestamp_keep_exit_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            proc = run_cli(project, "--notes", "legacy")
            self.assertEqual(proc.returncode, 2)
            self.assertIn("--notes was removed", proc.stderr)
            self.assertIn("Revision_Notes.md is user-managed", proc.stderr)
            proc = run_cli(project, "--non-interactive")
            self.assertEqual(proc.returncode, 2)
            self.assertIn("without prompting", proc.stderr)
            proc = run_cli(project, "--date", "2000-01-01T00:00:00Z")
            self.assertEqual(proc.returncode, 5)
            self.assertIn("predates revision creation", proc.stderr)


if __name__ == "__main__":
    unittest.main()
