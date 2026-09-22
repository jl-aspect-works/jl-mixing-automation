from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def write_project(root: Path) -> Path:
    project = root / "Clients" / "Human Client" / "Projects" / "Human Project"
    admin = project / "00_Admin"
    source = project / "01_Client_Files" / "Original_Delivery"
    work = project / "02_Audio_Preparation" / "Working_Audio"
    admin.mkdir(parents=True)
    source.mkdir(parents=True)
    work.mkdir(parents=True)
    manifest = {
        "metadata": {
            "schema": "mixing-project",
            "schema_version": "1.1.0",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "created_with": "jl-mixing 1.4.0",
            "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "project_id": "human-project",
        "project_name": "Human Project",
        "audio": {"sample_rate": 48000, "bit_depth": 24},
    }
    (admin / "project-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (admin / "Intake_Report.md").write_text(
        "# Intake Report\n\n<!-- BEGIN AUTOMATED SECTION -->\nold\n<!-- END AUTOMATED SECTION -->\n",
        encoding="utf-8",
    )
    return project


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "jl_mixing.validate_intake_cli", *args],
        cwd=cwd or ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


class ValidateIntakeCliTests(unittest.TestCase):
    def test_help_preserves_v14_surface(self) -> None:
        proc = run_cli("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, "")
        self.assertTrue(proc.stdout.startswith("Usage: validate-intake [options]\n"))
        self.assertIn("--no-duplicate-check", proc.stdout)
        self.assertIn("--dry-run", proc.stdout)

    def test_dry_run_discovers_project_and_does_not_mutate_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            source = project / "01_Client_Files" / "Original_Delivery"
            (source / "Notes.txt").write_text("notes\n", encoding="utf-8")
            report = project / "00_Admin" / "Intake_Report.md"
            before = report.read_bytes()
            cwd = project / "02_Audio_Preparation" / "Working_Audio"
            proc = run_cli("--dry-run", cwd=cwd)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, "")
            self.assertIn("## Intake Summary", proc.stdout)
            self.assertIn("Notes.txt", proc.stdout)
            self.assertEqual(report.read_bytes(), before)

    def test_success_updates_report_and_preserves_human_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            source = project / "01_Client_Files" / "Original_Delivery"
            (source / "Notes.txt").write_text("notes\n", encoding="utf-8")
            report = project / "00_Admin" / "Intake_Report.md"
            proc = run_cli("--project", str(project))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, "")
            self.assertTrue(proc.stdout.startswith("Intake validation completed.\n\n"))
            self.assertIn("Project:         Human Project\n", proc.stdout)
            self.assertIn("Files inspected: 1\n", proc.stdout)
            self.assertIn("Next:\n  Review 00_Admin/Intake_Report.md\n", proc.stdout)
            persisted = report.read_text(encoding="utf-8")
            self.assertIn("## Intake Summary", persisted)
            self.assertIn("Notes.txt", persisted)

    def test_removed_option_retains_argument_exit_code_and_guidance(self) -> None:
        proc = run_cli("--report-only")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Error: --report-only was removed in JL Mixing 1.1.", proc.stderr)
        self.assertIn("always report-only", proc.stderr)

    def test_unsupported_sample_rate_retains_validation_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            proc = run_cli("--project", str(project), "--expected-sample-rate", "12345")
            self.assertEqual(proc.returncode, 5)
            self.assertIn("Unsupported expected sample rate: 12345", proc.stderr)


if __name__ == "__main__":
    unittest.main()
