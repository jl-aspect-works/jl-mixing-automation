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


def write_workspace(root: Path, *, inherited_cd: bool = False) -> tuple[Path, Path]:
    (root / "Studio").mkdir(parents=True)
    (root / "Clients").mkdir()
    studio = {
        "metadata": {
            "schema": "mixing-studio",
            "schema_version": "1.1.0",
            "document_id": "11111111-1111-1111-1111-111111111111",
            "created_with": "jl-mixing 1.4.0",
            "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "studio_id": "human-studio",
        "studio_name": "Human Studio",
        "root_path": str(root),
        "defaults": {
            "mix_engineer": "Human Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud transfer", "requested_deliverables": ["main_mix", "instrumental"]},
        },
        "cli": {"change_directory_after_create": inherited_cd},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    client_root = root / "Clients" / "Human Client"
    (client_root / "Projects").mkdir(parents=True)
    client = {
        "metadata": {
            "schema": "mixing-client",
            "schema_version": "1.1.0",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "created_with": "jl-mixing 1.4.0",
            "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "client_id": "human-client",
        "client_name": "Human Client",
        "defaults": {
            "artist": "Human Artist",
            "audio": {"sample_rate": 96000, "bit_depth": 32, "file_format": "AIFF"},
            "delivery": {"method": "Portal", "requested_deliverables": ["main_mix", "stems"]},
        },
    }
    (client_root / "client.json").write_text(json.dumps(client), encoding="utf-8")
    return root, client_root


def run_cli(cwd: Path, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "jl_mixing.new_mix_cli", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


class NewMixCliTests(unittest.TestCase):
    def test_help_matches_human_command_surface(self) -> None:
        proc = run_cli(ROOT, "--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("new-mix PROJECT_NAME", proc.stdout)
        self.assertIn("--source PATH", proc.stdout)
        self.assertIn("--cd", proc.stdout)

    def test_dry_run_from_client_context_lists_plan_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, client = write_workspace(root / "studio")
            source = root / "incoming"
            source.mkdir()
            (source / "Audio.wav").write_bytes(b"audio")
            proc = run_cli(client, "Dry Mix", "--source", str(source), "--dry-run")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Dry run — no changes made.", proc.stdout)
            self.assertIn("Project ID:                 dry-mix", proc.stdout)
            self.assertIn("Artist:                     Human Artist", proc.stdout)
            self.assertIn("Current revision:           1", proc.stdout)
            self.assertIn("04_Revisions/Revision_01/Revision_Notes.md", proc.stdout)
            self.assertIn("Would copy into 01_Client_Files/Original_Delivery/:", proc.stdout)
            self.assertIn("Audio.wav", proc.stdout)
            self.assertIn("approve-mix", proc.stdout)
            self.assertFalse((client / "Projects" / "Dry Mix").exists())

    def test_create_by_client_id_preserves_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio, client = write_workspace(Path(tmp))
            proc = run_cli(
                studio,
                "--project", "Human Song",
                "--client", "human-client",
                "--artist", "Override Artist",
                "--engineer", "Override Engineer",
                "--sample-rate", "48000",
                "--bit-depth", "24",
                "--file-format", "WAV",
                "--deliverables", "main_mix,master",
                "--no-cd",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Project created successfully.", proc.stdout)
            self.assertIn("Automatic directory change: disabled", proc.stdout)
            self.assertIn("  approve-mix", proc.stdout)
            manifest = json.loads((client / "Projects" / "Human Song" / "00_Admin" / "project-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["artist"], "Override Artist")
            self.assertEqual(manifest["mix_engineer"], "Override Engineer")
            self.assertEqual(manifest["audio"], {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"})
            self.assertEqual(manifest["delivery"]["requested_deliverables"], ["main_mix", "master"])

    def test_explicit_cd_writes_shell_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, client = write_workspace(root / "studio")
            result_file = root / "cd-result.txt"
            result_file.write_text("", encoding="utf-8")
            proc = run_cli(client, "CD Song", "--cd", extra_env={"JL_MIXING_CD_RESULT_FILE": str(result_file.resolve())})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            expected = (client / "Projects" / "CD Song").resolve()
            self.assertEqual(result_file.read_text(encoding="utf-8").strip(), str(expected))
            next_section = proc.stdout.split("Next:\n", 1)[1]
            self.assertNotIn("  cd ", next_section)
            self.assertIn("  approve-mix", next_section)

    def test_inherited_cd_writes_shell_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, client = write_workspace(root / "studio", inherited_cd=True)
            result_file = root / "cd-result.txt"
            result_file.write_text("", encoding="utf-8")
            proc = run_cli(client, "Inherited CD", extra_env={"JL_MIXING_CD_RESULT_FILE": str(result_file.resolve())})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Automatic directory change: enabled", proc.stdout)
            self.assertEqual(result_file.read_text(encoding="utf-8").strip(), str((client / "Projects" / "Inherited CD").resolve()))

    def test_cd_conflicts_and_duplicate_project_name_forms_are_arguments_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = write_workspace(Path(tmp))
            for args in (
                ("Song", "--cd", "--no-cd"),
                ("Song", "--cd", "--dry-run"),
                ("Song", "--project", "Other"),
            ):
                proc = run_cli(client, *args)
                self.assertEqual(proc.returncode, 2)
                self.assertTrue(proc.stderr.startswith("Error:"))

    def test_removed_options_keep_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = write_workspace(Path(tmp))
            expectations = {
                "--project-type": "project manifest no longer stores a project type",
                "--daw": "no longer manages DAW identity",
                "--template": "03_DAW_Project/",
                "--non-interactive": "without prompting",
            }
            for option, text in expectations.items():
                proc = run_cli(client, "Song", option)
                self.assertEqual(proc.returncode, 2)
                self.assertIn(text, proc.stderr)


if __name__ == "__main__":
    unittest.main()
