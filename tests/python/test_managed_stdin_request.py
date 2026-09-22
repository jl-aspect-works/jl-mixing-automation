from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from jl_mixing.cli import _expand_managed_stdin
from jl_mixing.errors import ArgumentError


class ManagedStdinRequestTests(unittest.TestCase):
    def test_large_import_request_moves_variable_paths_off_process_argv(self) -> None:
        sources = [f"C:/delivery/{index:04}-{'long-name-' * 12}.wav" for index in range(500)]
        selected = [f"{index:04}-{'long-name-' * 12}.wav" for index in range(500)]
        payload = json.dumps(
            {
                "sources": sources,
                "selected_relative_paths": selected,
                "decisions": {"conflict-1": "replace"},
            }
        )
        process_args = [
            "client-files",
            "import-execute",
            "--json",
            "--request-stdin",
            "--source-kind",
            "files",
            "--plan-id",
            "plan-1",
            "--progress=stderr-json",
        ]
        self.assertLess(len(process_args), 12)
        self.assertGreater(len(payload), 100_000)

        with patch("sys.stdin", io.StringIO(payload)):
            expanded = _expand_managed_stdin(process_args)

        self.assertNotIn("--request-stdin", expanded)
        self.assertEqual(expanded.count("--source"), 500)
        self.assertEqual(expanded.count("--include-relative-path"), 500)
        self.assertIn("--decisions-json", expanded)
        self.assertEqual(expanded[0:2], ["client-files", "import-execute"])

    def test_large_reset_request_uses_same_stdin_contract(self) -> None:
        relative_paths = [f"folder/track-{index:04}-{'long-' * 10}.wav" for index in range(500)]
        payload = json.dumps({"relative_paths": relative_paths, "decisions": {}})
        process_args = [
            "audio-prep",
            "reset-execute",
            "--json",
            "--request-stdin",
            "--plan-id",
            "plan-2",
        ]

        with patch("sys.stdin", io.StringIO(payload)):
            expanded = _expand_managed_stdin(process_args)

        self.assertEqual(expanded.count("--relative-path"), 500)
        self.assertNotIn("--request-stdin", expanded)

    def test_stdin_request_rejects_non_string_path_arrays(self) -> None:
        payload = json.dumps({"sources": ["one.wav", 2]})
        with patch("sys.stdin", io.StringIO(payload)):
            with self.assertRaises(ArgumentError):
                _expand_managed_stdin(
                    [
                        "client-files",
                        "import-plan",
                        "--json",
                        "--request-stdin",
                        "--source-kind",
                        "files",
                    ]
                )


if __name__ == "__main__":
    unittest.main()
