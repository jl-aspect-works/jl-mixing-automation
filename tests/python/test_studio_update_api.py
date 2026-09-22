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
            "created_with": "jl-mixing 2.0.0",
            "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "studio_id": "api-studio",
        "studio_name": "API Studio",
        "root_path": str(root),
        "defaults": {
            "mix_engineer": "Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud transfer", "requested_deliverables": ["main_mix", "instrumental"]},
        },
        "cli": {"change_directory_after_create": False},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    return root


def run_cli(cwd: Path, *args: str, fail_at: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    if fail_at:
        env["JL_MIXING_FAIL_AT"] = fail_at
    return subprocess.run(
        [sys.executable, "-m", "jl_mixing.cli", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


class StudioUpdateApiTests(unittest.TestCase):
    def test_updates_only_editable_fields_and_preserves_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_studio(Path(tmp))
            path = root / "Studio" / "studio.json"
            before = json.loads(path.read_text(encoding="utf-8"))
            proc = run_cli(
                root, "studio", "update", "--json",
                "--name", "Renamed Studio",
                "--engineer", "New Engineer",
                "--sample-rate", "96000",
                "--bit-depth", "32",
                "--file-format", "aiff",
                "--delivery-method", "Secure upload",
                "--deliverables", "main_mix,stems",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["operation"], "studio.update")
            self.assertEqual(payload["status"], "success")
            after = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(after["studio_id"], before["studio_id"])
            self.assertEqual(after["root_path"], before["root_path"])
            self.assertEqual(after["cli"], before["cli"])
            for key in ("schema", "schema_version", "document_id", "created_with", "created_at"):
                self.assertEqual(after["metadata"][key], before["metadata"][key])
            self.assertNotEqual(after["metadata"]["last_modified_at"], before["metadata"]["last_modified_at"])
            self.assertEqual(after["studio_name"], "Renamed Studio")
            self.assertEqual(after["defaults"]["audio"], {"sample_rate": 96000, "bit_depth": 32, "file_format": "AIFF"})
            self.assertEqual(after["defaults"]["delivery"]["requested_deliverables"], ["main_mix", "stems"])

    def test_dry_run_validates_without_writing_or_touching_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_studio(Path(tmp))
            path = root / "Studio" / "studio.json"
            before = path.read_text(encoding="utf-8")
            proc = run_cli(root, "studio", "update", "--json", "--name", "Planned Name", "--dry-run")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["data"]["editable"]["studio_name"], "Planned Name")
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_invalid_value_is_blocked_and_original_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_studio(Path(tmp))
            path = root / "Studio" / "studio.json"
            before = path.read_bytes()
            proc = run_cli(root, "studio", "update", "--json", "--sample-rate", "12345")
            self.assertEqual(proc.returncode, 5)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["errors"][0]["code"], "VALIDATION_FAILED")
            self.assertEqual(path.read_bytes(), before)

    def test_transaction_failure_rolls_back_original_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_studio(Path(tmp))
            path = root / "Studio" / "studio.json"
            before = path.read_bytes()
            proc = run_cli(root, "studio", "update", "--json", "--name", "Should Roll Back", fail_at="after-file-replacement")
            self.assertNotEqual(proc.returncode, 0)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "error")
            self.assertEqual(path.read_bytes(), before)

    def test_requires_at_least_one_editable_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_studio(Path(tmp))
            proc = run_cli(root, "studio", "update", "--json")
            self.assertEqual(proc.returncode, 2)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["errors"][0]["code"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
