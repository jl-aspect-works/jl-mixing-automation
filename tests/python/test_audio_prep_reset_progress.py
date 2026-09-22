from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from jl_mixing.api import managed_client_files as api
from jl_mixing.errors import ValidationError


def events(output: io.StringIO) -> list[dict]:
    return [json.loads(line.removeprefix("JL_PROGRESS ")) for line in output.getvalue().splitlines() if line.startswith("JL_PROGRESS ")]


class AudioPrepResetProgressTests(unittest.TestCase):
    def test_skipped_files_do_not_make_finalization_counts_go_backwards(self) -> None:
        output = io.StringIO()
        adapter = api._ManagedExecutionProgressAdapter("audio.prep.reset.execute", 2, include_planning=True)
        with redirect_stderr(output):
            adapter.start()
            adapter({"phase": "planning", "completed": 2, "total": 2, "active": []})
            adapter({"phase": "staging", "completed": 2, "total": 2, "active": []})
            adapter({"phase": "importing", "completed": 2, "total": 2, "active": []})
            adapter({"phase": "finalizing", "completed": 1, "total": 1, "active": ["one.wav"]})
            adapter.finish()
        overall = [event["overall_completed"] for event in events(output)]
        self.assertEqual(overall, sorted(overall))
        self.assertEqual(overall[-1], 8)

    def test_execute_emits_real_counts_and_reserves_completion_until_engine_returns(self) -> None:
        request = api.ResetRequest(Path("/project"), ("one.wav", "two.wav"), "plan-id", {}, "stderr-json")
        plan = {"plan_id": "plan-id", "files": [{"relative_path": "one.wav"}, {"relative_path": "two.wav"}]}
        output = io.StringIO()

        def execute(_root, _plan, _decisions, *, progress=None):
            self.assertIsNotNone(progress)
            progress({"phase": "staging", "completed": 0, "total": 2, "active": ["one.wav"]})
            progress({"phase": "staging", "completed": 1, "total": 2, "active": ["one.wav"]})
            progress({"phase": "staging", "completed": 2, "total": 2, "active": ["two.wav"]})
            progress({"phase": "importing", "completed": 1, "total": 2, "active": ["one.wav"]})
            progress({"phase": "importing", "completed": 2, "total": 2, "active": []})
            progress({"phase": "finalizing", "completed": 2, "total": 2, "active": []})
            progress({"phase": "complete", "completed": 2, "total": 2, "active": []})
            self.assertLess(events(output)[-1]["overall_completed"], events(output)[-1]["overall_total"])
            return {"items": [], "invalidations": []}

        with (
            patch.object(api, "resolve_project", return_value=Path("/project")),
            patch.object(api, "plan_reset", return_value=plan) as plan_reset,
            patch.object(api, "execute_plan", side_effect=execute),
            patch.object(api, "_project_data", return_value={}),
            redirect_stderr(output),
        ):
            result, status = api.execute_reset(request)

        self.assertEqual(status, 0)
        self.assertEqual(result["status"], "success")
        reported = events(output)
        self.assertEqual(reported[0]["phase"], "planning")
        self.assertEqual(reported[0]["total"], 2)
        self.assertEqual(reported[0]["completed"], 0)
        plan_reset.assert_called_once()
        self.assertIsNotNone(plan_reset.call_args.kwargs["progress"])
        overall = [event["overall_completed"] for event in reported]
        self.assertEqual(overall, sorted(overall))
        self.assertEqual(reported[-1]["phase"], "complete")
        self.assertEqual(reported[-1]["overall_completed"], reported[-1]["overall_total"])
        self.assertTrue(all(event["operation"] == "audio.prep.reset.execute" for event in reported))

    def test_failure_never_reports_complete(self) -> None:
        request = api.ResetRequest(Path("/project"), ("one.wav",), "plan-id", {}, "stderr-json")
        output = io.StringIO()

        def execute(_root, _plan, _decisions, *, progress=None):
            progress({"phase": "staging", "completed": 1, "total": 1, "active": []})
            raise ValidationError("destination changed")

        with (
            patch.object(api, "resolve_project", return_value=Path("/project")),
            patch.object(api, "plan_reset", return_value={"plan_id": "plan-id", "files": [{"relative_path": "one.wav"}]}),
            patch.object(api, "execute_plan", side_effect=execute),
            redirect_stderr(output),
        ):
            result, status = api.execute_reset(request)
        self.assertNotEqual(status, 0)
        self.assertEqual(result["status"], "blocked")
        self.assertNotIn("complete", [event["phase"] for event in events(output)])

    def test_progress_option_is_execute_only(self) -> None:
        args = ["--json", "--relative-path", "one.wav", "--plan-id", "plan-id", "--progress=stderr-json"]
        self.assertEqual(api.parse_reset_args(args, execute=True).progress, "stderr-json")
        with self.assertRaisesRegex(api.ArgumentError, "execute-only"):
            api.parse_reset_args(["--json", "--relative-path", "one.wav", "--progress=stderr-json"], execute=False)


if __name__ == "__main__":
    unittest.main()
