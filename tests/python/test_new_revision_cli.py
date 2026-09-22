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


def write_project(root: Path, *, inherited_cd: bool = False) -> tuple[Path, Path]:
    (root / "Studio").mkdir(parents=True)
    (root / "Clients").mkdir()
    studio = {
        "metadata": {
            "schema": "mixing-studio", "schema_version": "1.1.0",
            "document_id": "11111111-1111-1111-1111-111111111111",
            "created_with": "jl-mixing 1.4.0", "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "studio_id": "human-studio", "studio_name": "Human Studio", "root_path": str(root),
        "defaults": {
            "mix_engineer": "Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
        "cli": {"change_directory_after_create": inherited_cd},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    client = root / "Clients" / "Human Client"
    (client / "Projects").mkdir(parents=True)
    client_doc = {
        "metadata": {
            "schema": "mixing-client", "schema_version": "1.1.0",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "created_with": "jl-mixing 1.4.0", "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "client_id": "human-client", "client_name": "Human Client",
        "defaults": {
            "artist": "Artist",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
    }
    (client / "client.json").write_text(json.dumps(client_doc), encoding="utf-8")
    project = create_project(ProjectCreateRequest(client, "Human Song", change_directory=False)).project_root
    return root, project


def run_cli(cwd: Path, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "jl_mixing.new_revision_cli", *args],
        cwd=cwd, env=env, text=True, capture_output=True, check=False,
    )


class NewRevisionCliTests(unittest.TestCase):
    def test_help_matches_human_command_surface(self) -> None:
        proc = run_cli(ROOT, "--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Usage: new-revision", proc.stdout)
        self.assertIn("--description TEXT", proc.stdout)
        self.assertIn("--source PATH", proc.stdout)
        self.assertIn("--cd", proc.stdout)

    def test_dry_run_lists_state_and_source_plan_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, project = write_project(root / "studio")
            source = root / "prints"
            source.mkdir()
            (source / "Mix.wav").write_bytes(b"mix")
            proc = run_cli(project, "--description", "Client notes", "--source", str(source), "--dry-run")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Dry run — no changes made.", proc.stdout)
            self.assertIn("Current revision:           1", proc.stdout)
            self.assertIn("New revision:               2", proc.stdout)
            self.assertIn("Description:                Client notes", proc.stdout)
            self.assertIn("Revision_02/Mix.wav", proc.stdout)
            transition = "->" if os.name == "nt" else "→"
            self.assertIn(f"state.current_revision: 1 {transition} 2", proc.stdout)
            self.assertIn("state.approved_revision: null", proc.stdout)
            self.assertIn("approve-mix", proc.stdout)
            self.assertFalse((project / "04_Revisions" / "Revision_02").exists())

    def test_create_from_explicit_project_and_no_cd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, project = write_project(Path(tmp))
            proc = run_cli(root, "--project", str(project), "--description", "More vocal", "--no-cd")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Revision created successfully.", proc.stdout)
            self.assertIn("Revision:                   2", proc.stdout)
            self.assertIn("Automatic directory change: disabled", proc.stdout)
            self.assertIn("Project state:              In progress", proc.stdout)
            self.assertTrue((project / "04_Revisions" / "Revision_02" / "Revision_Notes.md").is_file())
            manifest = json.loads((project / "00_Admin" / "project-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"]["current_revision"], 2)
            self.assertEqual(manifest["revisions"][-1]["description"], "More vocal")

    def test_explicit_cd_writes_shell_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, project = write_project(root / "studio")
            result_file = root / "cd-result.txt"
            result_file.write_text("", encoding="utf-8")
            proc = run_cli(project, "--cd", extra_env={"JL_MIXING_CD_RESULT_FILE": str(result_file.resolve())})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            expected = (project / "04_Revisions" / "Revision_02").resolve()
            self.assertEqual(result_file.read_text(encoding="utf-8").strip(), str(expected))
            next_section = proc.stdout.split("Next:\n", 1)[1]
            self.assertNotIn("  cd ", next_section)
            self.assertIn("  approve-mix", next_section)

    def test_inherited_cd_writes_shell_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, project = write_project(root / "studio", inherited_cd=True)
            result_file = root / "cd-result.txt"
            result_file.write_text("", encoding="utf-8")
            proc = run_cli(project, extra_env={"JL_MIXING_CD_RESULT_FILE": str(result_file.resolve())})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Automatic directory change: enabled", proc.stdout)
            self.assertEqual(
                result_file.read_text(encoding="utf-8").strip(),
                str((project / "04_Revisions" / "Revision_02").resolve()),
            )

    def test_cd_conflicts_and_removed_option_are_argument_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, project = write_project(Path(tmp))
            for args in (("--cd", "--no-cd"), ("--cd", "--dry-run")):
                proc = run_cli(project, *args)
                self.assertEqual(proc.returncode, 2)
                self.assertTrue(proc.stderr.startswith("Error:"))
            proc = run_cli(project, "--non-interactive")
            self.assertEqual(proc.returncode, 2)
            self.assertIn("removed in JL Mixing 1.1", proc.stderr)
            self.assertIn("without prompting", proc.stderr)


if __name__ == "__main__":
    unittest.main()
