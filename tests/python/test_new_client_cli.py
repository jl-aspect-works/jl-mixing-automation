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


def make_studio(root: Path, *, auto_cd: bool = False) -> None:
    (root / "Studio").mkdir(parents=True)
    (root / "Clients").mkdir()
    studio = {
        "metadata": {
            "schema": "mixing-studio",
            "schema_version": "1.1.0",
            "document_id": "00000000-0000-0000-0000-000000000001",
            "created_with": "jl-mixing 1.4.0",
            "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "studio_id": "test-studio",
        "studio_name": "Test Studio",
        "root_path": str(root),
        "defaults": {
            "mix_engineer": "Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {
                "method": "Cloud transfer",
                "requested_deliverables": ["main_mix", "instrumental"],
            },
        },
        "cli": {"change_directory_after_create": auto_cd},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")


def run_cli(cwd: Path, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    env.pop("JL_MIXING_ROOT", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "jl_mixing.new_client_cli", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


class NewClientCliTests(unittest.TestCase):
    def test_help_preserves_command_surface(self) -> None:
        proc = run_cli(ROOT, "--help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Usage: new-client CLIENT_ID [options]", proc.stdout)
        self.assertIn("--delivery-method TEXT", proc.stdout)
        self.assertIn("--root PATH", proc.stdout)
        self.assertIn("--cd", proc.stdout)

    def test_dry_run_inherits_defaults_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = Path(tmp)
            make_studio(studio)
            proc = run_cli(studio, "api-client", "--name", "API Client", "--dry-run")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Dry run — no changes made.", proc.stdout)
            self.assertIn("48000 Hz / 24-bit / WAV", proc.stdout)
            self.assertIn("main_mix, instrumental", proc.stdout)
            self.assertFalse((studio / "Clients" / "API Client").exists())

    def test_create_writes_canonical_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = Path(tmp)
            make_studio(studio)
            proc = run_cli(
                studio,
                "api-client",
                "--name", "API Client",
                "--artist", "Artist",
                "--sample-rate", "96000",
                "--bit-depth", "32",
                "--file-format", "aiff",
                "--delivery-method", "Drive",
                "--deliverables", "main_mix,stems",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            client_file = studio / "Clients" / "API Client" / "client.json"
            self.assertTrue(client_file.is_file())
            doc = json.loads(client_file.read_text(encoding="utf-8"))
            self.assertEqual(doc["client_id"], "api-client")
            self.assertEqual(doc["defaults"]["artist"], "Artist")
            self.assertEqual(doc["defaults"]["audio"], {"sample_rate": 96000, "bit_depth": 32, "file_format": "AIFF"})
            self.assertEqual(doc["defaults"]["delivery"]["requested_deliverables"], ["main_mix", "stems"])
            self.assertTrue((studio / "Clients" / "API Client" / "Projects").is_dir())
            self.assertIn("Client created successfully.", proc.stdout)

    def test_default_workspace_is_used_outside_studio_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            default_studio = home / "Music" / "Mixes"
            unrelated = base / "downloads"
            unrelated.mkdir()
            make_studio(default_studio)
            proc = run_cli(
                unrelated,
                "default-client",
                "--name", "Default Client",
                extra_env={"HOME": str(home), "USERPROFILE": str(home)},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((default_studio / "Clients" / "Default Client" / "client.json").is_file())

    def test_explicit_root_takes_precedence_over_environment_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            explicit = base / "explicit"
            configured = base / "configured"
            context = base / "context"
            make_studio(explicit)
            make_studio(configured)
            make_studio(context)
            proc = run_cli(
                context,
                "precedence-client",
                "--name", "Precedence Client",
                "--root", str(explicit),
                extra_env={"JL_MIXING_ROOT": str(configured)},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((explicit / "Clients" / "Precedence Client" / "client.json").is_file())
            self.assertFalse((configured / "Clients" / "Precedence Client").exists())
            self.assertFalse((context / "Clients" / "Precedence Client").exists())

    def test_environment_root_takes_precedence_over_current_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            configured = base / "configured"
            context = base / "context"
            make_studio(configured)
            make_studio(context)
            proc = run_cli(
                context,
                "environment-client",
                "--name", "Environment Client",
                extra_env={"JL_MIXING_ROOT": str(configured)},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((configured / "Clients" / "Environment Client" / "client.json").is_file())
            self.assertFalse((context / "Clients" / "Environment Client").exists())

    def test_invalid_explicit_root_fails_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            valid_studio = base / "studio"
            invalid_root = base / "missing"
            make_studio(valid_studio)
            proc = run_cli(valid_studio, "blocked-client", "--root", str(invalid_root))
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("No context marker", proc.stderr)
            self.assertFalse((valid_studio / "Clients" / "Blocked Client").exists())

    def test_cd_result_file_receives_created_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = Path(tmp) / "studio"
            studio.mkdir()
            make_studio(studio)
            result_file = Path(tmp) / "cd-result.txt"
            result_file.write_text("", encoding="utf-8")
            proc = run_cli(
                studio,
                "cd-client",
                "--name", "CD Client",
                "--cd",
                extra_env={"JL_MIXING_CD_RESULT_FILE": str(result_file)},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            expected = (studio / "Clients" / "CD Client").resolve()
            self.assertEqual(Path(result_file.read_text(encoding="utf-8").strip()).resolve(), expected)
            self.assertNotIn("integration is not active", proc.stdout)

    def test_inherited_cd_warns_when_shell_integration_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = Path(tmp)
            make_studio(studio, auto_cd=True)
            proc = run_cli(studio, "auto-client", "--name", "Auto Client")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Automatic directory change: enabled", proc.stdout)
            self.assertIn("integration is not active", proc.stdout)

    def test_cd_and_no_cd_conflict_is_argument_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = Path(tmp)
            make_studio(studio)
            proc = run_cli(studio, "client", "--cd", "--no-cd")
            self.assertEqual(proc.returncode, 2)
            self.assertIn("cannot be used together", proc.stderr)

    def test_dry_run_rejects_cd_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = Path(tmp)
            make_studio(studio)
            proc = run_cli(studio, "client", "--dry-run", "--cd")
            self.assertEqual(proc.returncode, 2)
            self.assertIn("cannot be used with --dry-run", proc.stderr)

    def test_removed_option_preserves_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = Path(tmp)
            make_studio(studio)
            proc = run_cli(studio, "client", "--revision-limit")
            self.assertEqual(proc.returncode, 2)
            self.assertIn("removed in JL Mixing 1.1", proc.stderr)


if __name__ == "__main__":
    unittest.main()
