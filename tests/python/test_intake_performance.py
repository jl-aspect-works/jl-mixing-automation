from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jl_mixing.intake_incremental import validate_intake_incremental

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

_METADATA = {
    "sample_rate": 48000,
    "bit_depth": 24,
    "channels": 1,
    "duration": 1.0,
    "codec_name": "pcm_s24le",
    "format_name": "wav",
}


def _write_project(root: Path) -> Path:
    project = root / "Clients" / "Progress Client" / "Projects" / "Progress Project"
    admin = project / "00_Admin"
    source = project / "01_Client_Files" / "Original_Delivery"
    admin.mkdir(parents=True)
    source.mkdir(parents=True)
    manifest = {
        "metadata": {
            "schema": "mixing-project",
            "schema_version": "1.1.0",
            "document_id": "11111111-1111-1111-1111-111111111111",
            "created_with": "jl-mixing test",
            "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "project_id": "progress-project",
        "project_name": "Progress Project",
        "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
    }
    (admin / "project-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (admin / "Intake_Report.md").write_text(
        "# Intake Report\n\n<!-- BEGIN AUTOMATED SECTION -->\nold\n<!-- END AUTOMATED SECTION -->\n",
        encoding="utf-8",
    )
    return project


class IntakePerformanceTests(unittest.TestCase):
    def test_unique_audio_avoids_full_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "One.wav").write_bytes(b"first unique audio payload")
            (source / "Two.wav").write_bytes(b"second different audio payload")
            with (
                patch("jl_mixing.intake.ffprobe_metadata", return_value=(_METADATA, None)),
                patch("jl_mixing.intake.ffmpeg_decode_check", return_value=None),
                patch("jl_mixing.intake.sha256_file", side_effect=AssertionError("unique file was fully hashed")),
            ):
                result = validate_intake_incremental(
                    source,
                    ffprobe_path="ffprobe",
                    ffmpeg_path="ffmpeg",
                )
            self.assertEqual(result.files_validated, 2)
            self.assertTrue(all(record["sha256"] is None for record in result.files))

    def test_duplicate_candidates_still_receive_exact_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            payload = b"identical audio payload"
            (source / "One.wav").write_bytes(payload)
            (source / "Two.wav").write_bytes(payload)
            with (
                patch("jl_mixing.intake.ffprobe_metadata", return_value=(_METADATA, None)),
                patch("jl_mixing.intake.ffmpeg_decode_check", return_value=None),
                patch("jl_mixing.intake.sha256_file", side_effect=lambda path: path.read_bytes().hex()) as digest,
            ):
                result = validate_intake_incremental(
                    source,
                    ffprobe_path="ffprobe",
                    ffmpeg_path="ffmpeg",
                )
            self.assertEqual(digest.call_count, 2)
            for record in result.files:
                self.assertIsInstance(record["sha256"], str)
                self.assertTrue(any(finding["code"] == "EXACT_DUPLICATE" for finding in record["findings"]))

    def test_progress_reports_inventory_completed_count_and_active_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "One.wav").write_bytes(b"one")
            (source / "Two.wav").write_bytes(b"two")
            events: list[dict[str, object]] = []
            with (
                patch("jl_mixing.intake.ffprobe_metadata", return_value=(_METADATA, None)),
                patch("jl_mixing.intake.ffmpeg_decode_check", return_value=None),
            ):
                validate_intake_incremental(
                    source,
                    ffprobe_path="ffprobe",
                    ffmpeg_path="ffmpeg",
                    progress=events.append,
                )
            self.assertEqual(events[0]["phase"], "scanning")
            determinate = [event for event in events if event.get("total") == 2]
            self.assertTrue(determinate)
            self.assertEqual(determinate[-1]["completed"], 2)
            self.assertLessEqual(max(len(event["active"]) for event in determinate), 2)
            active_names = {name for event in determinate for name in event["active"]}
            self.assertEqual(active_names, {"One.wav", "Two.wav"})

    def test_cli_progress_is_opt_in_on_stderr_and_stdout_stays_single_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _write_project(Path(tmp))
            source = project / "01_Client_Files" / "Original_Delivery"
            (source / "Notes.txt").write_text("notes\n", encoding="utf-8")
            env = os.environ.copy()
            env["PYTHONPATH"] = str(SRC)
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "jl_mixing.cli",
                    "intake",
                    "validate",
                    "--json",
                    "--project",
                    str(project),
                    "--progress=stderr-json",
                    "--dry-run",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["operation"], "intake.validate")
            progress_lines = [line for line in proc.stderr.splitlines() if line.startswith("JL_PROGRESS ")]
            self.assertGreaterEqual(len(progress_lines), 3)
            events = [json.loads(line.removeprefix("JL_PROGRESS ")) for line in progress_lines]
            self.assertTrue(all(event["operation"] == "intake.validate" for event in events))
            self.assertEqual(events[0]["phase"], "scanning")
            self.assertEqual(events[-1]["phase"], "finalizing")
            self.assertEqual(events[-1]["completed"], 1)
            self.assertEqual(events[-1]["total"], 1)


if __name__ == "__main__":
    unittest.main()
