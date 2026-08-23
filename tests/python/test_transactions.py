from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jl_mixing.errors import JLMixingError
from jl_mixing.transactions import commit_new_directory


class TransactionDirectoryCommitTests(unittest.TestCase):
    def test_new_directory_commit_uses_rename_not_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage = root / ".project.jl-stage-test"
            destination = root / "Project"
            stage.mkdir()
            (stage / "marker.txt").write_text("ok", encoding="utf-8")

            with patch(
                "jl_mixing.transactions.os.replace",
                side_effect=AssertionError("directory commit must not use replace semantics"),
            ):
                commit_new_directory(stage, destination)

            self.assertFalse(stage.exists())
            self.assertEqual((destination / "marker.txt").read_text(encoding="utf-8"), "ok")

    def test_directory_rename_failure_is_wrapped_as_domain_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage = root / ".project.jl-stage-test"
            destination = root / "Project"
            stage.mkdir()

            with patch(
                "jl_mixing.transactions.os.rename",
                side_effect=OSError(5, "Access is denied"),
            ):
                with self.assertRaises(JLMixingError) as context:
                    commit_new_directory(stage, destination)

            self.assertIn("Could not commit staged directory", str(context.exception))
            self.assertTrue(stage.is_dir())
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
