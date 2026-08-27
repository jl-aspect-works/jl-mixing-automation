from __future__ import annotations

import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jl_mixing import managed_client_files


class ManagedImportStagedMoveTests(unittest.TestCase):
    def _project_and_source(self, root: Path, content: bytes = b"new-audio") -> tuple[Path, Path]:
        project = root / "project"
        (project / "00_Admin").mkdir(parents=True)
        source = root / "mix.wav"
        source.write_bytes(content)
        return project, source

    def test_create_moves_original_and_copies_working_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, source = self._project_and_source(Path(tmp))
            plan = managed_client_files.plan_import(project, "files", (source,))

            with (
                patch.object(managed_client_files.diagnostic_log, "info") as info_log,
                patch.object(managed_client_files.diagnostic_log, "debug") as debug_log,
            ):
                result = managed_client_files.execute_plan(project, plan, {})

            self.assertEqual([item["result"] for item in result["items"]], ["created", "created"])
            self.assertEqual((project / managed_client_files.ORIGINAL_ROOT / "mix.wav").read_bytes(), b"new-audio")
            self.assertEqual((project / managed_client_files.AUDIO_ROOT / "mix.wav").read_bytes(), b"new-audio")

            profile = next(
                call.kwargs for call in info_log.call_args_list
                if call.args == ("managed_import_execute_profile",)
            )
            self.assertEqual(profile["moved_items"], 1)
            self.assertEqual(profile["copied_items"], 1)
            self.assertEqual(profile["moved_bytes"], len(b"new-audio"))
            self.assertEqual(profile["copied_bytes"], len(b"new-audio"))
            write_profiles = [
                call.kwargs for call in debug_log.call_args_list
                if call.args == ("managed_import_write_item_profile",)
            ]
            self.assertEqual([entry["transfer_method"] for entry in write_profiles], ["move", "copy"])

    def test_replace_moves_original_and_preserves_authoritative_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, source = self._project_and_source(Path(tmp))
            original = project / managed_client_files.ORIGINAL_ROOT / "mix.wav"
            working = project / managed_client_files.AUDIO_ROOT / "mix.wav"
            original.parent.mkdir(parents=True)
            working.parent.mkdir(parents=True)
            original.write_bytes(b"old-original")
            working.write_bytes(b"old-working")
            plan = managed_client_files.plan_import(project, "files", (source,))

            result = managed_client_files.execute_plan(
                project,
                plan,
                {"original:0": "replace", "audio:0": "replace"},
            )

            self.assertEqual([item["result"] for item in result["items"]], ["replaced", "replaced"])
            self.assertEqual(original.read_bytes(), b"new-audio")
            self.assertEqual(working.read_bytes(), b"new-audio")

    def test_skipped_original_skips_dependent_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, source = self._project_and_source(Path(tmp))
            original = project / managed_client_files.ORIGINAL_ROOT / "mix.wav"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"existing")
            plan = managed_client_files.plan_import(project, "files", (source,))

            result = managed_client_files.execute_plan(project, plan, {"original:0": "skip"})

            self.assertEqual([item["result"] for item in result["items"]], ["skipped", "skipped"])
            self.assertEqual(original.read_bytes(), b"existing")
            self.assertFalse((project / managed_client_files.AUDIO_ROOT / "mix.wav").exists())

    def test_failure_after_original_move_rolls_back_original_and_working(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, source = self._project_and_source(Path(tmp))
            original = project / managed_client_files.ORIGINAL_ROOT / "mix.wav"
            working = project / managed_client_files.AUDIO_ROOT / "mix.wav"
            original.parent.mkdir(parents=True)
            working.parent.mkdir(parents=True)
            original.write_bytes(b"old-original")
            working.write_bytes(b"old-working")
            plan = managed_client_files.plan_import(project, "files", (source,))

            with patch.object(managed_client_files.shutil, "copyfile", side_effect=OSError("injected copy failure")):
                with self.assertRaises(OSError):
                    managed_client_files.execute_plan(
                        project,
                        plan,
                        {"original:0": "replace", "audio:0": "replace"},
                    )

            self.assertEqual(original.read_bytes(), b"old-original")
            self.assertEqual(working.read_bytes(), b"old-working")

    def test_cross_device_original_move_falls_back_to_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, source = self._project_and_source(Path(tmp))
            plan = managed_client_files.plan_import(project, "files", (source,))
            real_replace = os.replace
            injected = False

            def replace_with_exdev(source_path: str | os.PathLike[str], destination_path: str | os.PathLike[str]) -> None:
                nonlocal injected
                source_candidate = Path(source_path)
                destination_candidate = Path(destination_path)
                if (
                    not injected
                    and ".jl-managed-import-" in source_candidate.as_posix()
                    and "/stage/" in source_candidate.as_posix()
                    and managed_client_files.ORIGINAL_ROOT.as_posix() in destination_candidate.as_posix()
                ):
                    injected = True
                    raise OSError(errno.EXDEV, "cross-device link")
                real_replace(source_path, destination_path)

            with (
                patch.object(managed_client_files.os, "replace", side_effect=replace_with_exdev),
                patch.object(managed_client_files.diagnostic_log, "info") as info_log,
                patch.object(managed_client_files.diagnostic_log, "debug") as debug_log,
            ):
                result = managed_client_files.execute_plan(project, plan, {})

            self.assertTrue(injected)
            self.assertEqual([item["result"] for item in result["items"]], ["created", "created"])
            self.assertEqual((project / managed_client_files.ORIGINAL_ROOT / "mix.wav").read_bytes(), b"new-audio")
            self.assertEqual((project / managed_client_files.AUDIO_ROOT / "mix.wav").read_bytes(), b"new-audio")
            profile = next(
                call.kwargs for call in info_log.call_args_list
                if call.args == ("managed_import_execute_profile",)
            )
            self.assertEqual(profile["moved_items"], 0)
            self.assertEqual(profile["copied_items"], 2)
            write_profiles = [
                call.kwargs for call in debug_log.call_args_list
                if call.args == ("managed_import_write_item_profile",)
            ]
            self.assertEqual([entry["transfer_method"] for entry in write_profiles], ["copy", "copy"])


if __name__ == "__main__":
    unittest.main()
