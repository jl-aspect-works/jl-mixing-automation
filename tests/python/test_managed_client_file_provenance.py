from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jl_mixing.managed_client_file_provenance import PROVENANCE_PATH, execute_plan, plan_import, plan_reset


def project_fixture(root: Path) -> Path:
    (root / "00_Admin").mkdir(parents=True)
    (root / "01_Client_Files" / "Original_Delivery").mkdir(parents=True)
    (root / "02_Audio_Preparation" / "Working_Audio").mkdir(parents=True)
    return root


class ManagedClientFileProvenanceTests(unittest.TestCase):
    def test_import_new_version_detects_renamed_audio_from_existing_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = project_fixture(Path(tmp) / "project")
            original = project / "01_Client_Files" / "Original_Delivery" / "Lead.wav"
            original.write_bytes(b"version-one")
            renamed = project / "02_Audio_Preparation" / "Working_Audio" / "Lead Clean.wav"
            renamed.write_bytes(b"version-one")
            incoming = Path(tmp) / "Lead.wav"
            incoming.write_bytes(b"version-two")

            plan = plan_import(project, "files", (incoming,))
            original_item = next(item for item in plan["items"] if item["area"] == "original_delivery")
            audio_item = next(item for item in plan["items"] if item["area"] == "audio_prep")

            self.assertTrue(original_item["conflict"])
            self.assertTrue(audio_item["conflict"])
            self.assertEqual(
                audio_item["destination_relative_path"],
                "02_Audio_Preparation/Working_Audio/Lead Clean.wav",
            )

            execute_plan(
                project,
                plan,
                {original_item["id"]: "replace", audio_item["id"]: "replace"},
            )
            self.assertEqual(renamed.read_bytes(), b"version-two")
            self.assertFalse((project / "02_Audio_Preparation" / "Working_Audio" / "Lead.wav").exists())
            provenance = json.loads((project / PROVENANCE_PATH).read_text(encoding="utf-8"))
            self.assertEqual(provenance["entries"][0]["source_relative_path"], "Lead.wav")
            self.assertEqual(
                provenance["entries"][0]["working_relative_path"],
                "02_Audio_Preparation/Working_Audio/Lead Clean.wav",
            )

    def test_reset_recovers_lineage_after_rename_even_when_source_content_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = project_fixture(Path(tmp) / "project")
            incoming = Path(tmp) / "Lead.wav"
            incoming.write_bytes(b"version-one")
            initial = plan_import(project, "files", (incoming,))
            execute_plan(project, initial, {})

            original = project / "01_Client_Files" / "Original_Delivery" / "Lead.wav"
            audio = project / "02_Audio_Preparation" / "Working_Audio" / "Lead.wav"
            renamed = audio.with_name("Lead Clean.wav")
            audio.rename(renamed)
            original.write_bytes(b"version-two")

            plan = plan_reset(project, ("Lead.wav",))
            item = plan["items"][0]
            self.assertTrue(item["conflict"])
            self.assertEqual(
                item["destination_relative_path"],
                "02_Audio_Preparation/Working_Audio/Lead Clean.wav",
            )

            execute_plan(project, plan, {item["id"]: "replace"})
            self.assertEqual(renamed.read_bytes(), b"version-two")
            self.assertFalse(audio.exists())

    def test_reset_keeps_lineage_when_working_file_was_repaired_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = project_fixture(Path(tmp) / "project")
            incoming = Path(tmp) / "Lead.wav"
            incoming.write_bytes(b"version-one")
            initial = plan_import(project, "files", (incoming,))
            execute_plan(project, initial, {})

            original = project / "01_Client_Files" / "Original_Delivery" / "Lead.wav"
            audio = project / "02_Audio_Preparation" / "Working_Audio" / "Lead.wav"

            # A validator repair may legitimately change working bytes. Identity stays
            # anchored to the Original Delivery source while the known working path survives.
            audio.write_bytes(b"repaired-working-audio")
            original.write_bytes(b"version-two")

            plan = plan_reset(project, ("Lead.wav",))
            item = plan["items"][0]
            self.assertTrue(item["conflict"])
            self.assertEqual(
                item["destination_relative_path"],
                "02_Audio_Preparation/Working_Audio/Lead.wav",
            )


if __name__ == "__main__":
    unittest.main()
