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


def write_workspace(root: Path) -> tuple[Path, Path]:
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
        "studio_id": "api-studio",
        "studio_name": "API Studio",
        "root_path": str(root),
        "defaults": {
            "mix_engineer": "API Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud transfer", "requested_deliverables": ["main_mix", "instrumental"]},
        },
        "cli": {"change_directory_after_create": True},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")

    client_root = root / "Clients" / "API Client"
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
        "client_id": "api-client",
        "client_name": "API Client",
        "defaults": {
            "artist": "API Artist",
            "audio": {"sample_rate": 96000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Portal", "requested_deliverables": ["main_mix", "stems"]},
        },
    }
    (client_root / "client.json").write_text(json.dumps(client), encoding="utf-8")
    return root, client_root


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


class ProjectApiTests(unittest.TestCase):
    def test_dry_run_from_client_context_is_structured_and_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = write_workspace(Path(tmp))
            proc = run_cli(client, "project", "create", "Dry Song", "--json", "--dry-run")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, "")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["operation"], "project.create")
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["data"]["project"]["id"], "dry-song")
            self.assertEqual(payload["data"]["project"]["artist"], "API Artist")
            self.assertEqual(payload["data"]["client"]["id"], "api-client")
            self.assertEqual(len(payload["data"]["would_create"]), 3)
            self.assertFalse((client / "Projects" / "Dry Song").exists())

    def test_client_id_resolution_from_studio_context_and_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio, client = write_workspace(Path(tmp))
            proc = run_cli(
                studio,
                "project", "create", "--project", "Created Song", "--client", "api-client", "--json",
                "--artist", "Override Artist", "--sample-rate", "48000", "--deliverables", "main_mix,master",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["data"]["project"]["name"], "Created Song")
            self.assertEqual(payload["data"]["project"]["artist"], "Override Artist")
            self.assertEqual(Path(payload["data"]["project"]["path"]), (client / "Projects" / "Created Song").resolve())
            manifest = json.loads((client / "Projects" / "Created Song" / "00_Admin" / "project-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["audio"]["sample_rate"], 48000)
            self.assertEqual(manifest["delivery"]["requested_deliverables"], ["main_mix", "master"])

    def test_duplicate_project_is_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = write_workspace(Path(tmp))
            first = run_cli(client, "project", "create", "Duplicate Song", "--json")
            self.assertEqual(first.returncode, 0, first.stderr)
            second = run_cli(client, "project", "create", "Different Name", "--project-id", "duplicate-song", "--json")
            self.assertEqual(second.returncode, 5)
            self.assertEqual(second.stderr, "")
            payload = json.loads(second.stdout)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["errors"][0]["code"], "PROJECT_ALREADY_EXISTS")

    def test_missing_client_id_is_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio, _ = write_workspace(Path(tmp))
            proc = run_cli(studio, "project", "create", "Song", "--client", "missing-client", "--json")
            self.assertEqual(proc.returncode, 4)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["errors"][0]["code"], "CLIENT_NOT_FOUND")

    def test_json_mode_rejects_shell_cd_and_duplicate_name_forms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = write_workspace(Path(tmp))
            proc = run_cli(client, "project", "create", "Song", "--json", "--cd")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(json.loads(proc.stdout)["errors"][0]["code"], "INVALID_REQUEST")
            proc = run_cli(client, "project", "create", "Song", "--project", "Other", "--json")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(json.loads(proc.stdout)["errors"][0]["code"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
