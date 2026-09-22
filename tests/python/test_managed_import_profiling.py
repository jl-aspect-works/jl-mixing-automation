from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jl_mixing import managed_client_files


class ManagedImportProfilingTests(unittest.TestCase):
    def test_plan_and_execute_emit_timing_profiles_without_changing_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / "00_Admin").mkdir(parents=True)
            source = root / "mix.wav"
            source.write_bytes(b"audio-data")

            with patch.object(managed_client_files.diagnostic_log, "info") as info_log:
                plan = managed_client_files.plan_import(project, "files", (source,))

            plan_profile = next(
                call for call in info_log.call_args_list
                if call.args == ("managed_import_plan_profile",)
            )
            plan_fields = plan_profile.kwargs
            self.assertEqual(plan_fields["source_kind"], "files")
            self.assertEqual(plan_fields["file_count"], 1)
            self.assertEqual(plan_fields["total_bytes"], len(b"audio-data"))
            self.assertEqual(plan_fields["item_count"], 2)
            self.assertGreaterEqual(plan_fields["collect_ms"], 0)
            self.assertGreaterEqual(plan_fields["destination_check_ms"], 0)
            self.assertGreaterEqual(plan_fields["total_ms"], 0)

            with (
                patch.object(managed_client_files.diagnostic_log, "info") as info_log,
                patch.object(managed_client_files.diagnostic_log, "debug") as debug_log,
            ):
                result = managed_client_files.execute_plan(project, plan, {})

            self.assertEqual(
                [item["result"] for item in result["items"]],
                ["created", "created"],
            )
            self.assertEqual(
                (project / "01_Client_Files" / "Original_Delivery" / "mix.wav").read_bytes(),
                b"audio-data",
            )
            self.assertEqual(
                (project / "02_Audio_Preparation" / "Working_Audio" / "mix.wav").read_bytes(),
                b"audio-data",
            )

            execute_profile = next(
                call for call in info_log.call_args_list
                if call.args == ("managed_import_execute_profile",)
            )
            execute_fields = execute_profile.kwargs
            self.assertTrue(execute_fields["success"])
            self.assertEqual(execute_fields["file_count"], 1)
            self.assertEqual(execute_fields["staged_bytes"], len(b"audio-data"))
            self.assertEqual(execute_fields["written_bytes"], len(b"audio-data") * 2)
            self.assertEqual(execute_fields["created_count"], 2)
            self.assertEqual(execute_fields["replaced_count"], 0)
            self.assertEqual(execute_fields["skipped_count"], 0)
            for field in (
                "setup_ms",
                "transaction_setup_ms",
                "staging_ms",
                "importing_ms",
                "invalidation_ms",
                "cleanup_ms",
                "total_ms",
            ):
                self.assertGreaterEqual(execute_fields[field], 0)

            debug_events = [call.args[0] for call in debug_log.call_args_list]
            self.assertIn("managed_import_stage_file_profile", debug_events)
            self.assertEqual(debug_events.count("managed_import_write_item_profile"), 2)


if __name__ == "__main__":
    unittest.main()
