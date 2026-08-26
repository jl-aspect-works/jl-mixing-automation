from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def fixture(root: Path) -> Path:
    (root / "Studio").mkdir(parents=True)
    client = root / "Clients" / "Client"
    project = client / "Projects" / "Project"
    (project / "00_Admin").mkdir(parents=True)
    (project / "01_Client_Files" / "Original_Delivery").mkdir(parents=True)
    (project / "02_Audio_Preparation" / "Working_Audio").mkdir(parents=True)
    studio = {"metadata":{"schema":"mixing-studio","schema_version":"1.1.0","document_id":"44444444-4444-4444-4444-444444444444","created_with":"jl-mixing 2.0.0","created_at":"2030-01-01T12:00:00Z","last_modified_at":"2030-01-01T12:00:00Z"},"studio_id":"studio","studio_name":"Studio","root_path":str(root),"defaults":{"mix_engineer":"Engineer","audio":{"sample_rate":48000,"bit_depth":24,"file_format":"WAV"},"delivery":{"method":"Cloud","requested_deliverables":["main_mix"]}},"cli":{"change_directory_after_create":False}}
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    client_doc = {"metadata":{"schema":"mixing-client","schema_version":"1.1.0","document_id":"55555555-5555-4555-8555-555555555555","created_with":"jl-mixing 2.0.0","created_at":"2030-01-01T12:00:00Z","last_modified_at":"2030-01-01T12:00:00Z"},"client_id":"client","client_name":"Client","defaults":{"artist":"Artist","audio":{"sample_rate":48000,"bit_depth":24,"file_format":"WAV"},"delivery":{"method":"Cloud","requested_deliverables":["main_mix"]}}}
    client.mkdir(parents=True, exist_ok=True)
    (client / "client.json").write_text(json.dumps(client_doc), encoding="utf-8")
    manifest = {"metadata":{"schema":"mixing-project","schema_version":"1.1.0","document_id":"66666666-6666-4666-8666-666666666666","created_with":"jl-mixing 2.0.0","created_at":"2030-01-01T12:00:00Z","last_modified_at":"2030-01-01T12:00:00Z"},"project_id":"project","project_name":"Project","client":{"client_document_id":client_doc["metadata"]["document_id"],"client_id":"client"},"artist":"Artist","album":"","producer":"","mix_engineer":"Engineer","music":{"bpm":120,"key":"C","time_signature":"4/4"},"audio":{"sample_rate":48000,"bit_depth":24,"file_format":"WAV"},"delivery":{"method":"Cloud","requested_deliverables":["main_mix"]},"schedule":{"deadline":None},"creative_direction":"","state":{"current_revision":1,"approved_revision":None,"delivered_revision":None},"revisions":[]}
    (project / "00_Admin" / "project-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return project


def run(cwd: Path, *args: str):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run([sys.executable, "-m", "jl_mixing.cli", *args], cwd=cwd, env=env, text=True, capture_output=True, check=False)


class ManagedClientFilesApiTests(unittest.TestCase):
    def test_folder_plan_execute_preserves_paths_and_populates_audio_prep(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); project = fixture(root / "studio")
            source = root / "delivery"; (source / "Stems").mkdir(parents=True)
            (source / "mix.wav").write_bytes(b"mix")
            (source / "Stems" / "bass.wav").write_bytes(b"bass")
            planned = run(project, "client-files", "import-plan", "--json", "--source-kind", "folder", "--source", str(source))
            self.assertEqual(planned.returncode, 0, planned.stderr)
            plan = json.loads(planned.stdout)["data"]["plan"]
            self.assertEqual(len(plan["items"]), 4)
            self.assertFalse(any(item["conflict"] for item in plan["items"]))
            executed = run(project, "client-files", "import-execute", "--json", "--source-kind", "folder", "--source", str(source), "--plan-id", plan["plan_id"])
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertEqual((project / "01_Client_Files" / "Original_Delivery" / "Stems" / "bass.wav").read_bytes(), b"bass")
            self.assertEqual((project / "02_Audio_Preparation" / "Working_Audio" / "mix.wav").read_bytes(), b"mix")

    def test_folder_execute_can_select_only_part_of_the_immutable_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); project = fixture(root / "studio")
            source = root / "delivery"; (source / "Stems").mkdir(parents=True)
            (source / "mix.wav").write_bytes(b"mix")
            (source / "Stems" / "bass.wav").write_bytes(b"bass")
            planned = run(project, "client-files", "import-plan", "--json", "--source-kind", "folder", "--source", str(source))
            plan = json.loads(planned.stdout)["data"]["plan"]
            executed = run(
                project,
                "client-files", "import-execute", "--json", "--source-kind", "folder", "--source", str(source),
                "--plan-id", plan["plan_id"], "--include-relative-path", "Stems/bass.wav",
            )
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertEqual((project / "01_Client_Files" / "Original_Delivery" / "Stems" / "bass.wav").read_bytes(), b"bass")
            self.assertEqual((project / "02_Audio_Preparation" / "Working_Audio" / "Stems" / "bass.wav").read_bytes(), b"bass")
            self.assertFalse((project / "01_Client_Files" / "Original_Delivery" / "mix.wav").exists())
            self.assertFalse((project / "02_Audio_Preparation" / "Working_Audio" / "mix.wav").exists())

    def test_selection_rejects_unknown_paths_and_ignores_deselected_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); project = fixture(root / "studio")
            source = root / "delivery"; source.mkdir()
            (source / "keep.wav").write_bytes(b"keep")
            (source / "conflict.wav").write_bytes(b"new")
            existing = project / "01_Client_Files" / "Original_Delivery" / "conflict.wav"
            existing.write_bytes(b"old")
            planned = run(project, "client-files", "import-plan", "--json", "--source-kind", "folder", "--source", str(source))
            plan = json.loads(planned.stdout)["data"]["plan"]

            unknown = run(
                project,
                "client-files", "import-execute", "--json", "--source-kind", "folder", "--source", str(source),
                "--plan-id", plan["plan_id"], "--include-relative-path", "missing.wav",
            )
            self.assertEqual(unknown.returncode, 5)
            self.assertIn("Selected import path is not part of the plan", unknown.stdout)

            executed = run(
                project,
                "client-files", "import-execute", "--json", "--source-kind", "folder", "--source", str(source),
                "--plan-id", plan["plan_id"], "--include-relative-path", "keep.wav",
            )
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertEqual(existing.read_bytes(), b"old")
            self.assertEqual((project / "01_Client_Files" / "Original_Delivery" / "keep.wav").read_bytes(), b"keep")
            self.assertEqual((project / "02_Audio_Preparation" / "Working_Audio" / "keep.wav").read_bytes(), b"keep")

    def test_conflicts_require_decisions_and_skip_couples_audio_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); project = fixture(root / "studio")
            source = root / "mix.wav"; source.write_bytes(b"new")
            original = project / "01_Client_Files" / "Original_Delivery" / "mix.wav"; original.write_bytes(b"old")
            planned = run(project, "client-files", "import-plan", "--json", "--source-kind", "files", "--source", str(source))
            plan = json.loads(planned.stdout)["data"]["plan"]
            conflict = next(item for item in plan["items"] if item["area"] == "original_delivery")
            missing = run(project, "client-files", "import-execute", "--json", "--source-kind", "files", "--source", str(source), "--plan-id", plan["plan_id"])
            self.assertEqual(missing.returncode, 5)
            decisions = json.dumps({conflict["id"]: "skip"})
            executed = run(project, "client-files", "import-execute", "--json", "--source-kind", "files", "--source", str(source), "--plan-id", plan["plan_id"], "--decisions-json", decisions)
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertEqual(original.read_bytes(), b"old")
            self.assertFalse((project / "02_Audio_Preparation" / "Working_Audio" / "mix.wav").exists())

    def test_reset_replaces_audio_only_and_invalidates_audio_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = fixture(Path(tmp))
            original = project / "01_Client_Files" / "Original_Delivery" / "mix.wav"; original.write_bytes(b"source")
            audio = project / "02_Audio_Preparation" / "Working_Audio" / "mix.wav"; audio.write_bytes(b"edited")
            cache = project / "00_Admin" / "audio-prep-validation-cache.json"; cache.write_text("{}", encoding="utf-8")
            planned = run(project, "audio-prep", "reset-plan", "--json", "--relative-path", "mix.wav")
            plan = json.loads(planned.stdout)["data"]["plan"]
            conflict = plan["items"][0]
            executed = run(project, "audio-prep", "reset-execute", "--json", "--relative-path", "mix.wav", "--plan-id", plan["plan_id"], "--decisions-json", json.dumps({conflict["id"]:"replace"}))
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertEqual(audio.read_bytes(), b"source")
            self.assertEqual(original.read_bytes(), b"source")
            self.assertFalse(cache.exists())

    def test_reset_targets_renamed_audio_prep_file_by_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = fixture(Path(tmp))
            original = project / "01_Client_Files" / "Original_Delivery" / "Lead Vocal.wav"
            original.write_bytes(b"same-audio-content")
            renamed = project / "02_Audio_Preparation" / "Working_Audio" / "Vox Lead.wav"
            renamed.write_bytes(b"same-audio-content")

            planned = run(project, "audio-prep", "reset-plan", "--json", "--relative-path", "Lead Vocal.wav")
            self.assertEqual(planned.returncode, 0, planned.stdout + planned.stderr)
            plan = json.loads(planned.stdout)["data"]["plan"]
            item = plan["items"][0]
            self.assertTrue(item["conflict"])
            self.assertEqual(item["destination_relative_path"], "02_Audio_Preparation/Working_Audio/Vox Lead.wav")

            executed = run(project, "audio-prep", "reset-execute", "--json", "--relative-path", "Lead Vocal.wav", "--plan-id", plan["plan_id"], "--decisions-json", json.dumps({item["id"]:"replace"}))
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertTrue(renamed.exists())
            self.assertFalse((project / "02_Audio_Preparation" / "Working_Audio" / "Lead Vocal.wav").exists())

    def test_reset_refuses_ambiguous_duplicate_audio_prep_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = fixture(Path(tmp))
            original = project / "01_Client_Files" / "Original_Delivery" / "mix.wav"; original.write_bytes(b"same")
            audio_root = project / "02_Audio_Preparation" / "Working_Audio"
            (audio_root / "one.wav").write_bytes(b"same")
            (audio_root / "two.wav").write_bytes(b"same")
            planned = run(project, "audio-prep", "reset-plan", "--json", "--relative-path", "mix.wav")
            self.assertEqual(planned.returncode, 5)
            self.assertIn("Multiple Audio Prep files match", planned.stdout)

    def test_zip_traversal_and_stale_plan_are_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); project = fixture(root / "studio")
            bad = root / "bad.zip"
            with zipfile.ZipFile(bad, "w") as archive: archive.writestr("../escape.wav", b"bad")
            blocked = run(project, "client-files", "import-plan", "--json", "--source-kind", "zip", "--source", str(bad))
            self.assertEqual(blocked.returncode, 6)
            source = root / "mix.wav"; source.write_bytes(b"one")
            planned = run(project, "client-files", "import-plan", "--json", "--source-kind", "files", "--source", str(source))
            plan = json.loads(planned.stdout)["data"]["plan"]
            source.write_bytes(b"changed")
            stale = run(project, "client-files", "import-execute", "--json", "--source-kind", "files", "--source", str(source), "--plan-id", plan["plan_id"])
            self.assertEqual(stale.returncode, 5)

    def test_import_execute_progress_is_opt_in_and_preserves_stdout_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = fixture(root / "studio")
            source = root / "delivery"
            source.mkdir()
            (source / "one.wav").write_bytes(b"one")
            (source / "two.wav").write_bytes(b"two")
            planned = run(project, "client-files", "import-plan", "--json", "--source-kind", "folder", "--source", str(source))
            plan = json.loads(planned.stdout)["data"]["plan"]
            executed = run(project, "client-files", "import-execute", "--json", "--source-kind", "folder", "--source", str(source), "--plan-id", plan["plan_id"], "--progress=stderr-json")
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            payload = json.loads(executed.stdout)
            self.assertEqual(payload["operation"], "client.files.import.execute")
            lines = [line for line in executed.stderr.splitlines() if line.startswith("JL_PROGRESS ")]
            self.assertGreaterEqual(len(lines), 3)
            events = [json.loads(line.removeprefix("JL_PROGRESS ")) for line in lines]
            self.assertTrue(all(event["operation"] == "client.files.import.execute" for event in events))
            staging_completed = [event["completed"] for event in events if event["phase"] == "staging"]
            self.assertEqual(staging_completed[0], 0)
            self.assertEqual(staging_completed[-1], 2)
            self.assertIn(1, staging_completed)
            self.assertEqual(events[-1]["phase"], "complete")
            self.assertEqual(events[-1]["completed"], 2)
            self.assertEqual(events[-1]["total"], 2)

    def test_discovery_advertises_managed_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = fixture(Path(tmp))
            info = run(project, "system-info", "--json")
            self.assertEqual(info.returncode, 0, info.stderr)
            capabilities = set(json.loads(info.stdout)["capabilities"])
            self.assertTrue({"client.files.import.plan","client.files.import.execute","audio.prep.reset.plan","audio.prep.reset.execute"}.issubset(capabilities))


if __name__ == "__main__":
    unittest.main()
