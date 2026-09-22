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


def run_cli(cwd: Path, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "jl_mixing.new_studio_cli", *args],
        cwd=cwd, env=env, text=True, capture_output=True, check=False,
    )


class NewStudioCliTests(unittest.TestCase):
    def test_help_matches_human_command_surface(self) -> None:
        proc = run_cli(ROOT, "--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Usage: new-studio", proc.stdout)
        self.assertIn("--default-cd", proc.stdout)
        self.assertIn("--no-default-cd", proc.stdout)

    def test_dry_run_is_non_mutating_and_reports_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            target = parent / "My Studio"
            proc = run_cli(
                parent,
                "--root", str(target),
                "--name", "My Studio",
                "--engineer", "Mix Engineer",
                "--sample-rate", "96000",
                "--bit-depth", "32",
                "--file-format", "aiff",
                "--default-cd",
                "--dry-run",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            expected_heading = "Dry run - no changes made." if os.name == "nt" else "Dry run — no changes made."
            self.assertIn(expected_heading, proc.stdout)
            self.assertIn("Studio:                     My Studio", proc.stdout)
            self.assertIn("Audio format:               96000 Hz / 32-bit / AIFF", proc.stdout)
            self.assertIn("Automatic directory change: enabled", proc.stdout)
            self.assertIn("Shell integration:           not detected", proc.stdout)
            self.assertIn("Studio/studio.json", proc.stdout)
            self.assertFalse(target.exists())

    def test_create_writes_minimal_workspace_and_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            target = parent / "Studio Root"
            proc = run_cli(parent, "--root", str(target), "--name", "JL Room", "--engineer", "Jake", "--no-default-cd")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Studio created successfully.", proc.stdout)
            self.assertTrue((target / "Clients").is_dir())
            self.assertTrue((target / "Studio").is_dir())
            config_path = target / "Studio" / "studio.json"
            self.assertTrue(config_path.is_file())
            document = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(document["metadata"]["schema"], "mixing-studio")
            self.assertEqual(document["metadata"]["schema_version"], "1.1.0")
            self.assertEqual(document["studio_id"], "jl-room")
            self.assertEqual(document["root_path"], os.path.abspath(os.path.expanduser(str(target))))
            self.assertEqual(document["defaults"]["mix_engineer"], "Jake")
            self.assertFalse(document["cli"]["change_directory_after_create"])
            self.assertEqual(sorted(path.name for path in target.iterdir()), ["Clients", "Studio"])

    def test_existing_root_is_refused_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            marker = target / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            proc = run_cli(Path(tmp), "--root", str(target))
            self.assertEqual(proc.returncode, 6)
            self.assertIn("Studio root already exists", proc.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_validation_and_argument_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            cases = (
                (5, ("--root", str(parent / "a"), "--sample-rate", "12345")),
                (5, ("--root", str(parent / "b"), "--bit-depth", "20")),
                (5, ("--root", str(parent / "c"), "--file-format", "mp3")),
                (2, ("--root", str(parent / "d"), "--default-cd", "--no-default-cd")),
            )
            for expected, args in cases:
                proc = run_cli(parent, *args)
                self.assertEqual(proc.returncode, expected, proc.stderr)

    def test_removed_options_keep_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            for option, text in {
                "--daw": "DAW projects and templates are no longer managed",
                "--non-interactive": "without prompting",
            }.items():
                proc = run_cli(parent, "--root", str(parent / option.removeprefix("--")), option)
                self.assertEqual(proc.returncode, 2)
                self.assertIn(text, proc.stderr)


if __name__ == "__main__":
    unittest.main()
