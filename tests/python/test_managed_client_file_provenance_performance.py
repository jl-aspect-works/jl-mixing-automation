from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jl_mixing import managed_client_file_provenance as provenance
from jl_mixing import managed_client_files as base


class ManagedClientFileProvenancePerformanceTests(unittest.TestCase):
    def _project(self, root: Path) -> Path:
        project = root / "project"
        (project / base.ORIGINAL_ROOT).mkdir(parents=True)
        (project / base.AUDIO_ROOT).mkdir(parents=True)
        (project / "00_Admin").mkdir(parents=True)
        return project

    def test_reset_hashes_each_working_file_at_most_once_per_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            originals = project / base.ORIGINAL_ROOT
            working = project / base.AUDIO_ROOT
            (originals / "one.wav").write_bytes(b"1111")
            (originals / "two.wav").write_bytes(b"2222")
            (working / "renamed-one.wav").write_bytes(b"1111")
            (working / "renamed-two.wav").write_bytes(b"2222")

            real_hash = base._sha256_file
            with patch.object(base, "_sha256_file", wraps=real_hash) as mocked_hash:
                plan = provenance.plan_reset(project, ("one.wav", "two.wav"))

            destinations = {item["destination_relative_path"] for item in plan["items"]}
            self.assertEqual(destinations, {
                "02_Audio_Preparation/Working_Audio/renamed-one.wav",
                "02_Audio_Preparation/Working_Audio/renamed-two.wav",
            })
            hashed_paths = [Path(call.args[0]) for call in mocked_hash.call_args_list]
            self.assertEqual(hashed_paths.count(working / "renamed-one.wav"), 1)
            self.assertEqual(hashed_paths.count(working / "renamed-two.wav"), 1)

    def test_direct_provenance_does_not_build_content_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            originals = project / base.ORIGINAL_ROOT
            working = project / base.AUDIO_ROOT
            (originals / "one.wav").write_bytes(b"source")
            (working / "renamed.wav").write_bytes(b"edited")
            document = {
                "schema_version": provenance.SCHEMA_VERSION,
                "entries": [{
                    "source_relative_path": "one.wav",
                    "working_relative_path": "02_Audio_Preparation/Working_Audio/renamed.wav",
                    "source_sha256": "unused",
                    "working_sha256": "unused",
                    "transformations": ["copied"],
                }],
            }
            (project / provenance.PROVENANCE_PATH).write_text(json.dumps(document), encoding="utf-8")

            with patch.object(base, "_sha256_file") as mocked_hash:
                plan = provenance.plan_reset(project, ("one.wav",))

            self.assertEqual(
                plan["items"][0]["destination_relative_path"],
                "02_Audio_Preparation/Working_Audio/renamed.wav",
            )
            mocked_hash.assert_not_called()


if __name__ == "__main__":
    unittest.main()
