from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from jl_mixing import managed_client_files as managed_base
from jl_mixing.audio_prep_status import build_audio_prep_status
from jl_mixing.delivery import plan_delivery
from jl_mixing.errors import ValidationError
from jl_mixing.intake import validate_intake
from jl_mixing.managed_client_file_provenance import _WorkingHashIndex
from jl_mixing.managed_client_files import plan_import
from jl_mixing.os_metadata import is_ignored_os_metadata_name
from jl_mixing.revision_source import build_plan as build_revision_source_plan
from jl_mixing.source_import import build_plan as build_project_source_plan


IGNORED_NAMES = (".DS_Store", "._Mix.mp3", "Thumbs.db", "desktop.ini")


def _write_source_noise(root: Path) -> None:
    for name in IGNORED_NAMES:
        (root / name).write_bytes(b"metadata")


class OsMetadataFilteringTests(unittest.TestCase):
    def test_policy_is_platform_neutral_and_preserves_other_dotfiles(self) -> None:
        for name in (*IGNORED_NAMES, "THUMBS.DB", "Desktop.INI"):
            with self.subTest(name=name):
                self.assertTrue(is_ignored_os_metadata_name(name))

        for name in (".gitignore", ".mix-notes", "DS_Store", "Thumbs.db.txt", "mix._draft.wav"):
            with self.subTest(name=name):
                self.assertFalse(is_ignored_os_metadata_name(name))

    def test_delivery_selection_ignores_metadata_in_root_and_variants(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            revision = root / "Revision_01"
            delivery = root / "Delivery"
            variants = revision / "Variants"
            variants.mkdir(parents=True)
            delivery.mkdir()
            (revision / "Mix.mp3").write_bytes(b"mix")
            _write_source_noise(revision)
            (variants / "Instrumental.mp3").write_bytes(b"variant")
            (variants / "._Instrumental.mp3").write_bytes(b"metadata")

            plan = plan_delivery(
                revision,
                delivery,
                {"delivery": {"requested_deliverables": []}},
                mode="default",
                working_prefix="WORK ",
                includes=(),
                excludes=(),
                zip_name=None,
            )

            self.assertEqual(
                {record.source_path for record in plan.selected},
                {"Mix.mp3", "Variants/Instrumental.mp3"},
            )
            self.assertFalse(any(record.name in IGNORED_NAMES for record in plan.excluded))

    def test_intake_inventory_ignores_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "intake"
            source.mkdir()
            (source / ".mix-notes").write_text("keep", encoding="utf-8")
            _write_source_noise(source)

            result = validate_intake(
                source,
                duplicate_check=False,
                ffprobe_path="",
                ffmpeg_path="",
                update_cache=False,
            )

            self.assertEqual(result.files_discovered, 1)
            self.assertEqual([record["relative_path"] for record in result.files], [".mix-notes"])
            for name in IGNORED_NAMES:
                self.assertNotIn(name, result.report_markdown)

    def test_managed_folder_and_zip_imports_ignore_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            source = root / "source"
            source.mkdir()
            (source / "Mix.wav").write_bytes(b"mix")
            (source / ".mix-notes").write_text("keep", encoding="utf-8")
            _write_source_noise(source)

            folder_plan = plan_import(project, "folder", (source,))
            self.assertEqual(
                [record["relative_path"] for record in folder_plan["files"]],
                [".mix-notes", "Mix.wav"],
            )

            archive = root / "source.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                for path in source.iterdir():
                    handle.write(path, path.name)

            zip_plan = plan_import(project, "zip", (archive,))
            self.assertEqual(
                [record["relative_path"] for record in zip_plan["files"]],
                [".mix-notes", "Mix.wav"],
            )

    def test_explicit_managed_metadata_only_import_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            metadata = root / ".DS_Store"
            metadata.write_bytes(b"metadata")

            with self.assertRaisesRegex(ValidationError, "contains no files"):
                plan_import(project, "files", (metadata,))

    def test_project_and_revision_source_plans_ignore_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            (source / "Mix.wav").write_bytes(b"mix")
            (source / ".mix-notes").write_text("keep", encoding="utf-8")
            _write_source_noise(source)

            project_plan = build_project_source_plan(source)
            project_files = {entry.path for entry in project_plan.entries if entry.type == "file"}
            self.assertEqual(project_files, {"Mix.wav", ".mix-notes"})

            revision_plan = build_revision_source_plan(source)
            self.assertEqual(set(revision_plan.files), {"Mix.wav", ".mix-notes"})

    def test_audio_prep_with_only_metadata_is_empty_not_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            working = project / "02_Audio_Preparation" / "Working_Audio"
            working.mkdir(parents=True)
            _write_source_noise(working)

            status = build_audio_prep_status(
                project,
                original_files=[],
                expected_sample_rate=48000,
                expected_bit_depth=24,
                expected_format="wav",
                update_cache=False,
            )

            self.assertEqual(status["summary"]["files_discovered"], 0)
            self.assertEqual(status["summary"]["blocking_errors"], 0)
            self.assertEqual(status["files"], [])

    def test_provenance_recovery_ignores_metadata_content_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            working = project / "02_Audio_Preparation" / "Working_Audio"
            working.mkdir(parents=True)
            primary = working / "Mix.wav"
            primary.write_bytes(b"same-content")
            (working / "._Mix.wav").write_bytes(b"same-content")

            digest = managed_base._sha256_file(primary)
            match = _WorkingHashIndex(project).match(
                digest,
                ambiguity_message="OS metadata must not create a false provenance ambiguity",
            )

            self.assertEqual(match, "02_Audio_Preparation/Working_Audio/Mix.wav")


if __name__ == "__main__":
    unittest.main()
