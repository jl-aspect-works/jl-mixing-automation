from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from jl_mixing.api import managed_client_files as api


def progress_events(stderr: str) -> list[dict[str, object]]:
    return [
        json.loads(line.removeprefix("JL_PROGRESS "))
        for line in stderr.splitlines()
        if line.startswith("JL_PROGRESS ")
    ]


class ManagedImportProgressContractTests(unittest.TestCase):
    def test_adapter_uses_engine_counts_and_reserves_completion_for_true_end(self) -> None:
        output = io.StringIO()
        adapter = api._ImportProgressAdapter("client.files.import.execute", 2)

        with redirect_stderr(output):
            adapter({"phase": "staging", "completed": 0, "total": 2, "active": ["one.wav"]})
            adapter({"phase": "staging", "completed": 1, "total": 2, "active": ["one.wav"]})
            adapter({"phase": "staging", "completed": 1, "total": 2, "active": ["two.wav"]})
            adapter({"phase": "staging", "completed": 2, "total": 2, "active": ["two.wav"]})
            adapter({"phase": "importing", "completed": 0, "total": 2, "active": []})
            adapter({"phase": "importing", "completed": 1, "total": 2, "active": ["one.wav"]})
            adapter({"phase": "importing", "completed": 2, "total": 2, "active": []})
            adapter({"phase": "finalizing", "completed": 1, "total": 2, "active": ["one.wav"]})
            adapter({"phase": "finalizing", "completed": 2, "total": 2, "active": ["two.wav"]})
            adapter({"phase": "complete", "completed": 2, "total": 2, "active": []})
            adapter.finish()

        events = progress_events(output.getvalue())
        phases = [event["phase"] for event in events]
        self.assertEqual(phases[-2:], ["finalizing", "complete"])
        staging = [int(event["completed"]) for event in events if event["phase"] == "staging"]
        self.assertEqual(staging, [0, 1, 1, 2])
        finalizing = [int(event["completed"]) for event in events if event["phase"] == "finalizing"]
        self.assertEqual(finalizing, [1, 2])
        overall = [int(event["overall_completed"]) for event in events]
        self.assertEqual(overall, sorted(overall))
        self.assertTrue(all(event["overall_total"] == 6 for event in events))
        self.assertTrue(all(value < 6 for value in overall[:-1]))
        self.assertEqual(overall[-1], 6)
        self.assertEqual(events[-1]["completed"], 2)
        self.assertEqual(events[-1]["total"], 2)

    def test_execute_import_emits_determinate_replan_before_copy_and_complete_last(self) -> None:
        request = api.ImportRequest(
            project=Path("/project"),
            source_kind="files",
            sources=(Path("/source/one.wav"),),
            plan_id="plan-id",
            progress="stderr-json",
        )
        plan = {
            "plan_id": "plan-id",
            "files": [{"relative_path": "one.wav"}],
            "items": [],
        }
        output = io.StringIO()

        def fake_plan_import(*_args, progress=None):
            events = progress_events(output.getvalue())
            self.assertEqual(events[0]["phase"], "planning")
            self.assertIsNone(events[0]["total"])
            self.assertIsNone(events[0]["overall_total"])
            assert progress is not None
            progress({"phase": "planning", "completed": 1, "total": 2, "active": ["one.wav"]})
            progress({"phase": "planning", "completed": 2, "total": 2, "active": ["one.wav"]})
            return plan

        def fake_execute_plan(_root, _plan, _decisions, *, progress=None):
            assert progress is not None
            progress({"phase": "staging", "completed": 0, "total": 1, "active": ["one.wav"]})
            progress({"phase": "staging", "completed": 1, "total": 1, "active": ["one.wav"]})
            progress({"phase": "importing", "completed": 1, "total": 1, "active": []})
            progress({"phase": "finalizing", "completed": 1, "total": 1, "active": ["one.wav"]})
            progress({"phase": "complete", "completed": 1, "total": 1, "active": []})
            return {"items": []}

        with (
            patch.object(api, "resolve_project", return_value=Path("/project")),
            patch.object(api, "plan_import", side_effect=fake_plan_import),
            patch.object(api, "execute_plan", side_effect=fake_execute_plan),
            patch.object(api, "_project_data", return_value={"path": "/project", "workspace_path": "/workspace"}),
            redirect_stderr(output),
        ):
            payload, status = api.execute_import(request)

        self.assertEqual(status, 0)
        self.assertEqual(payload["status"], "success")
        events = progress_events(output.getvalue())
        planning = [event for event in events if event["phase"] == "planning"]
        self.assertEqual([event["completed"] for event in planning[-2:]], [1, 2])
        self.assertEqual([event["total"] for event in planning[-2:]], [2, 2])
        self.assertEqual(events[-2]["phase"], "finalizing")
        self.assertEqual(events[-1]["phase"], "complete")
        self.assertEqual(events[-1]["overall_completed"], events[-1]["overall_total"])

    def test_import_plan_accepts_progress_mode(self) -> None:
        parsed = api.parse_import_args(
            [
                "--json",
                "--project",
                "/project",
                "--source-kind",
                "files",
                "--source",
                "/source/one.wav",
                "--progress=stderr-json",
            ],
            execute=False,
        )
        self.assertEqual(parsed.progress, "stderr-json")

    def test_failed_import_never_emits_complete(self) -> None:
        request = api.ImportRequest(
            project=Path("/project"),
            source_kind="files",
            sources=(Path("/source/one.wav"),),
            plan_id="plan-id",
            progress="stderr-json",
        )
        plan = {"plan_id": "plan-id", "files": [{"relative_path": "one.wav"}], "items": []}
        output = io.StringIO()

        with (
            patch.object(api, "resolve_project", return_value=Path("/project")),
            patch.object(api, "plan_import", return_value=plan),
            patch.object(api, "execute_plan", side_effect=api.ValidationError("failed")),
            redirect_stderr(output),
        ):
            payload, status = api.execute_import(request)

        self.assertNotEqual(status, 0)
        self.assertEqual(payload["status"], "blocked")
        self.assertNotIn("complete", [event["phase"] for event in progress_events(output.getvalue())])


if __name__ == "__main__":
    unittest.main()
