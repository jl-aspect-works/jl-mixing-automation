from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from jl_mixing import managed_client_file_provenance as provenance


class ImportProvenanceHashReuseTests(unittest.TestCase):
    def test_zip_import_reuses_staged_hash_for_both_provenance_copies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / "00_Admin").mkdir(parents=True)
            archive = root / "delivery.zip"
            payload = b"representative-audio-content" * 4096
            info = zipfile.ZipInfo("mix.wav")
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr(info, payload)

            plan = provenance.plan_import(project, "zip", (archive,))
            info_events: list[tuple[str, dict[str, object]]] = []

            def capture_info(event: str, **fields: object) -> None:
                info_events.append((event, fields))

            with (
                patch.object(provenance.base, "_sha256_file", side_effect=AssertionError("destination content was reread for hashing")),
                patch.object(provenance.diagnostic_log, "info", side_effect=capture_info),
            ):
                result = provenance.execute_plan(project, plan, {})

            self.assertTrue(all(item["result"] == "created" for item in result["items"]))
            expected_hash = hashlib.sha256(payload).hexdigest()
            document = json.loads((project / provenance.PROVENANCE_PATH).read_text(encoding="utf-8"))
            self.assertEqual(len(document["entries"]), 1)
            entry = document["entries"][0]
            self.assertEqual(entry["source_sha256"], expected_hash)
            self.assertEqual(entry["working_sha256"], expected_hash)

            original = project / "01_Client_Files" / "Original_Delivery" / "mix.wav"
            working = project / "02_Audio_Preparation" / "Working_Audio" / "mix.wav"
            self.assertEqual(original.read_bytes(), payload)
            self.assertEqual(working.read_bytes(), payload)

            finalize = next(fields for event, fields in info_events if event == "managed_import_provenance_finalize_profile")
            self.assertEqual(finalize["hashed_bytes"], 0)
            self.assertEqual(finalize["reused_hash_count"], 1)
            self.assertEqual(finalize["reused_hash_bytes"], len(payload) * 2)
            self.assertEqual(finalize["source_hash_ms"], 0.0)
            self.assertEqual(finalize["working_hash_ms"], 0.0)

    def test_lineage_finalization_falls_back_to_destination_hashing_without_staged_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            source = root / "mix.wav"
            source.write_bytes(b"fallback-content")
            (project / "00_Admin").mkdir(parents=True)

            plan = provenance.plan_import(project, "files", (source,))
            result = provenance.base.execute_plan(project, plan, {})

            with patch.object(provenance.base, "_sha256_file", wraps=provenance.base._sha256_file) as sha256_file:
                provenance._record_successful_lineage(project, plan, result)

            self.assertEqual(sha256_file.call_count, 2)
            document = json.loads((project / provenance.PROVENANCE_PATH).read_text(encoding="utf-8"))
            entry = document["entries"][0]
            expected_hash = hashlib.sha256(b"fallback-content").hexdigest()
            self.assertEqual(entry["source_sha256"], expected_hash)
            self.assertEqual(entry["working_sha256"], expected_hash)


if __name__ == "__main__":
    unittest.main()
