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


def write_studio(root: Path) -> Path:
    (root / "Studio").mkdir(parents=True)
    (root / "Clients").mkdir()
    studio = {
        "metadata": {
            "schema": "mixing-studio",
            "schema_version": "1.1.0",
            "document_id": "44444444-4444-4444-4444-444444444444",
            "created_with": "jl-mixing 1.4.0",
            "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "studio_id": "api-studio",
        "studio_name": "API Studio",
        "root_path": str(root),
        "defaults": {
            "mix_engineer": "Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {
                "method": "Cloud transfer",
                "requested_deliverables": ["main_mix", "instrumental"],
            },
        },
        "cli": {"change_directory_after_create": False},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    return root


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


class ClientApiTests(unittest.TestCase):
    def test_dry_run_is_structured_and_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = write_studio(Path(tmp))
            proc = run_cli(studio, "client", "create", "api-client", "--json", "--dry-run")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, "")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["operation"], "client.create")
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["data"]["client"]["id"], "api-client")
            client_path = Path(payload["data"]["client"]["path"])
            self.assertFalse(client_path.exists())
            self.assertEqual(
                [Path(item).name for item in payload["data"]["would_create"]],
                ["client.json", "Projects"],
            )

    def test_explicit_studio_context_does_not_depend_on_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as unrelated:
            studio = write_studio(Path(tmp))
            proc = run_cli(
                Path(unrelated),
                "client",
                "create",
                "explicit-client",
                "--json",
                "--studio",
                str(studio),
                "--dry-run",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, "")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(Path(payload["data"]["workspace_path"]), studio)
            self.assertEqual(payload["data"]["client"]["id"], "explicit-client")

    def test_system_info_advertises_explicit_client_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = run_cli(Path(tmp), "system-info", "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertIn("client.create.explicit-context", payload["capabilities"])

    def test_success_commits_authoritative_client_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = write_studio(Path(tmp))
            proc = run_cli(
                studio,
                "client", "create", "api-client", "--json",
                "--name", "API Client",
                "--artist", "API Artist",
                "--sample-rate", "96000",
                "--bit-depth", "32",
                "--file-format", "aiff",
                "--deliverables", "main_mix,stems",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, "")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "success")
            client_path = Path(payload["data"]["client"]["path"])
            self.assertTrue((client_path / "Projects").is_dir())
            document = json.loads((client_path / "client.json").read_text(encoding="utf-8"))
            self.assertEqual(document["client_id"], "api-client")
            self.assertEqual(document["defaults"]["artist"], "API Artist")
            self.assertEqual(document["defaults"]["audio"]["sample_rate"], 96000)
            self.assertEqual(document["defaults"]["audio"]["file_format"], "AIFF")
            self.assertEqual(document["defaults"]["delivery"]["requested_deliverables"], ["main_mix", "stems"])

    def test_duplicate_client_returns_stable_blocked_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = write_studio(Path(tmp))
            first = run_cli(studio, "client", "create", "same-client", "--json")
            self.assertEqual(first.returncode, 0, first.stderr)
            proc = run_cli(studio, "client", "create", "same-client", "--json", "--name", "Other Name")
            self.assertEqual(proc.returncode, 5)
            self.assertEqual(proc.stderr, "")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["errors"][0]["code"], "CLIENT_ALREADY_EXISTS")
            self.assertEqual(payload["errors"][0]["details"]["exit_code"], 5)

    def test_json_mode_rejects_parent_shell_cd_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = write_studio(Path(tmp))
            proc = run_cli(studio, "client", "create", "api-client", "--json", "--cd")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stderr, "")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "error")
            self.assertEqual(payload["errors"][0]["code"], "INVALID_REQUEST")

    def test_json_flag_is_required_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio = write_studio(Path(tmp))
            proc = run_cli(studio, "client", "create", "api-client")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stderr, "")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["errors"][0]["code"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
