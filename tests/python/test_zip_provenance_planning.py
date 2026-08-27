from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from jl_mixing import managed_client_file_provenance as provenance


class ZipProvenancePlanningTests(unittest.TestCase):
    def test_zip_container_is_not_hashed_as_member_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / "00_Admin").mkdir(parents=True)
            archive = root / "delivery.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("mix.wav", b"audio-data")
                handle.writestr("Stems/bass.wav", b"bass-data")

            with patch.object(provenance.base, "_sha256_file", wraps=provenance.base._sha256_file) as sha256_file:
                plan = provenance.plan_import(project, "zip", (archive,))

            self.assertEqual(len(plan["files"]), 2)
            self.assertFalse(any(call.args and call.args[0] == archive for call in sha256_file.call_args_list))

    def test_existing_original_delivery_remains_valid_fallback_for_zip_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            original = project / "01_Client_Files" / "Original_Delivery" / "mix.wav"
            working = project / "02_Audio_Preparation" / "Working_Audio" / "renamed.wav"
            (project / "00_Admin").mkdir(parents=True)
            original.parent.mkdir(parents=True)
            working.parent.mkdir(parents=True)
            original.write_bytes(b"same-audio")
            working.write_bytes(b"same-audio")
            archive = root / "delivery.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("mix.wav", b"new-audio")

            plan = provenance.plan_import(project, "zip", (archive,))
            audio_item = next(item for item in plan["items"] if item["area"] == "audio_prep")

            self.assertEqual(
                audio_item["destination_relative_path"],
                "02_Audio_Preparation/Working_Audio/renamed.wav",
            )


if __name__ == "__main__":
    unittest.main()
