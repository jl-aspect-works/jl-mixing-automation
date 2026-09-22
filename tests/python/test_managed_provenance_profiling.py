from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jl_mixing import managed_client_file_provenance as provenance


class ManagedProvenanceProfilingTests(unittest.TestCase):
    def test_plan_and_execute_emit_provenance_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / "00_Admin").mkdir(parents=True)
            source = root / "mix.wav"
            source.write_bytes(b"audio-data")

            with (
                patch.object(provenance.diagnostic_log, "info") as info_log,
                patch.object(provenance.diagnostic_log, "debug") as debug_log,
            ):
                plan = provenance.plan_import(project, "files", (source,))

            events = [call.args[0] for call in info_log.call_args_list]
            self.assertIn("managed_import_provenance_plan_profile", events)
            self.assertIn("managed_import_working_hash_index_profile", events)
            plan_profile = next(
                call for call in info_log.call_args_list
                if call.args == ("managed_import_provenance_plan_profile",)
            ).kwargs
            self.assertEqual(plan_profile["source_kind"], "files")
            self.assertEqual(plan_profile["file_count"], 1)
            self.assertGreaterEqual(plan_profile["resolution_ms"], 0)
            self.assertGreaterEqual(plan_profile["total_ms"], 0)
            self.assertIn(
                "managed_import_fallback_hash_profile",
                [call.args[0] for call in debug_log.call_args_list],
            )

            with (
                patch.object(provenance.diagnostic_log, "info") as info_log,
                patch.object(provenance.diagnostic_log, "debug") as debug_log,
            ):
                result = provenance.execute_plan(project, plan, {})

            self.assertEqual(
                [item["result"] for item in result["items"]],
                ["created", "created"],
            )
            events = [call.args[0] for call in info_log.call_args_list]
            self.assertIn("managed_import_provenance_finalize_profile", events)
            self.assertIn("managed_import_provenance_execute_profile", events)
            finalize_profile = next(
                call for call in info_log.call_args_list
                if call.args == ("managed_import_provenance_finalize_profile",)
            ).kwargs
            self.assertEqual(finalize_profile["recorded_count"], 1)
            self.assertEqual(finalize_profile["hashed_bytes"], 0)
            self.assertEqual(finalize_profile["reused_hash_count"], 1)
            self.assertEqual(finalize_profile["reused_hash_bytes"], len(b"audio-data") * 2)
            self.assertEqual(finalize_profile["source_hash_ms"], 0.0)
            self.assertEqual(finalize_profile["working_hash_ms"], 0.0)
            hash_profile = next(
                call for call in debug_log.call_args_list
                if call.args == ("managed_import_provenance_hash_file_profile",)
            ).kwargs
            self.assertTrue(hash_profile["reused_staged_hash"])


if __name__ == "__main__":
    unittest.main()
