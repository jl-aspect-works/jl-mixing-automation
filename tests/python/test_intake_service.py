from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jl_mixing.intake_incremental import validate_intake_incremental


class IntakeServiceTests(unittest.TestCase):
    def test_empty_source_preserves_blocking_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            result = validate_intake_incremental(source, ffprobe_path="", ffmpeg_path="")
            self.assertTrue(result.blocked)
            self.assertEqual(result.files_discovered, 0)
            self.assertEqual(result.blocking_errors, 1)
            self.assertIn("No files were found in the intake source.", result.report_markdown)

    def test_non_audio_file_is_structured_as_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "Notes.txt").write_text("notes\n", encoding="utf-8")
            result = validate_intake_incremental(source, ffprobe_path="", ffmpeg_path="")
            self.assertEqual(result.files_discovered, 1)
            self.assertEqual(result.files[0]["relative_path"], "Notes.txt")
            self.assertEqual(result.files[0]["status"], "not_applicable")
            self.assertFalse(result.files[0]["is_audio"])

    def test_unchanged_audio_reuses_cached_expensive_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            audio = source / "Lead.wav"
            audio.write_bytes(b"audio-data-for-cache")
            cache = root / "intake-cache.json"
            metadata = {
                "sample_rate": 48000,
                "bit_depth": 24,
                "channels": 1,
                "duration": 1.0,
                "codec_name": "pcm_s24le",
                "format_name": "wav",
            }

            with (
                patch("jl_mixing.intake.ffprobe_metadata", return_value=(metadata, None)) as probe,
                patch("jl_mixing.intake.ffmpeg_decode_check", return_value=None) as decode,
            ):
                first = validate_intake_incremental(
                    source,
                    expected_sample_rate=48000,
                    expected_bit_depth=24,
                    expected_format="WAV",
                    ffprobe_path="ffprobe",
                    ffmpeg_path="ffmpeg",
                    cache_path=cache,
                )
            self.assertEqual(first.files_validated, 1)
            self.assertEqual(first.cache_reused, 0)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(decode.call_count, 1)

            with (
                patch("jl_mixing.intake.ffprobe_metadata", side_effect=AssertionError("probe reran")),
                patch("jl_mixing.intake.ffmpeg_decode_check", side_effect=AssertionError("decode reran")),
                patch("jl_mixing.intake.sha256_file", side_effect=AssertionError("hash reran")),
            ):
                second = validate_intake_incremental(
                    source,
                    expected_sample_rate=48000,
                    expected_bit_depth=24,
                    expected_format="WAV",
                    ffprobe_path="ffprobe",
                    ffmpeg_path="ffmpeg",
                    cache_path=cache,
                )
            self.assertEqual(second.files_validated, 0)
            self.assertEqual(second.cache_reused, 1)
            self.assertEqual(second.files[0]["cache_state"], "reused")
            self.assertEqual(second.files[0]["status"], "valid")

    def test_same_size_same_timestamp_content_change_invalidates_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            audio = source / "Lead.wav"
            audio.write_bytes(b"AAAAAAAAAAAAAAAA")
            cache = root / "intake-cache.json"
            metadata = {
                "sample_rate": 48000,
                "bit_depth": 24,
                "channels": 1,
                "duration": 1.0,
                "codec_name": "pcm_s24le",
                "format_name": "wav",
            }
            with (
                patch("jl_mixing.intake.ffprobe_metadata", return_value=(metadata, None)),
                patch("jl_mixing.intake.ffmpeg_decode_check", return_value=None),
            ):
                validate_intake_incremental(
                    source,
                    ffprobe_path="ffprobe",
                    ffmpeg_path="ffmpeg",
                    cache_path=cache,
                )
            original_stat = audio.stat()
            audio.write_bytes(b"BBBBBBBBBBBBBBBB")
            os.utime(audio, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

            with (
                patch("jl_mixing.intake.ffprobe_metadata", return_value=(metadata, None)) as probe,
                patch("jl_mixing.intake.ffmpeg_decode_check", return_value=None) as decode,
            ):
                result = validate_intake_incremental(
                    source,
                    ffprobe_path="ffprobe",
                    ffmpeg_path="ffmpeg",
                    cache_path=cache,
                )
            self.assertEqual(result.files_validated, 1)
            self.assertEqual(result.cache_reused, 0)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(decode.call_count, 1)

    def test_exact_duplicate_content_is_structured_per_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "Lead.wav").write_bytes(b"same audio")
            (source / "Lead Copy.wav").write_bytes(b"same audio")
            metadata = {
                "sample_rate": 48000,
                "bit_depth": 24,
                "channels": 1,
                "duration": 1.0,
                "codec_name": "pcm_s24le",
                "format_name": "wav",
            }
            with (
                patch("jl_mixing.intake.ffprobe_metadata", return_value=(metadata, None)),
                patch("jl_mixing.intake.ffmpeg_decode_check", return_value=None),
            ):
                result = validate_intake_incremental(
                    source,
                    expected_sample_rate=48000,
                    expected_bit_depth=24,
                    expected_format="WAV",
                    ffprobe_path="ffprobe",
                    ffmpeg_path="ffmpeg",
                )
            self.assertEqual(result.files_discovered, 2)
            for record in result.files:
                duplicates = [item for item in record["findings"] if item["code"] == "EXACT_DUPLICATE"]
                self.assertEqual(len(duplicates), 1)
                self.assertEqual(record["status"], "info")
                self.assertEqual(len(duplicates[0]["related_paths"]), 1)

    def test_current_project_expectations_invalidate_policy_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "Lead.wav").write_bytes(b"audio-data")
            cache = root / "intake-cache.json"
            metadata = {
                "sample_rate": 48000,
                "bit_depth": 24,
                "channels": 1,
                "duration": 1.0,
                "codec_name": "pcm_s24le",
                "format_name": "wav",
            }
            with (
                patch("jl_mixing.intake.ffprobe_metadata", return_value=(metadata, None)),
                patch("jl_mixing.intake.ffmpeg_decode_check", return_value=None),
            ):
                first = validate_intake_incremental(
                    source,
                    expected_sample_rate=48000,
                    expected_bit_depth=24,
                    expected_format="WAV",
                    ffprobe_path="ffprobe",
                    ffmpeg_path="ffmpeg",
                    cache_path=cache,
                )
            self.assertEqual(first.files[0]["status"], "valid")

            with (
                patch("jl_mixing.intake.ffprobe_metadata", return_value=(metadata, None)) as probe,
                patch("jl_mixing.intake.ffmpeg_decode_check", return_value=None) as decode,
            ):
                second = validate_intake_incremental(
                    source,
                    expected_sample_rate=44100,
                    expected_bit_depth=16,
                    expected_format="AIFF",
                    ffprobe_path="ffprobe",
                    ffmpeg_path="ffmpeg",
                    cache_path=cache,
                )
            self.assertEqual(second.files_validated, 1)
            self.assertEqual(second.cache_reused, 0)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(decode.call_count, 1)
            codes = {finding["code"] for finding in second.files[0]["findings"]}
            self.assertIn("SAMPLE_RATE_MISMATCH", codes)
            self.assertIn("BIT_DEPTH_MISMATCH", codes)
            self.assertIn("FILE_FORMAT_MISMATCH", codes)


if __name__ == "__main__":
    unittest.main()
