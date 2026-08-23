from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from jl_mixing.api.project_create import ProjectApiRequest, execute


class ProjectApiFailureTests(unittest.TestCase):
    def test_filesystem_failure_returns_structured_api_error(self) -> None:
        request = ProjectApiRequest(project_name="Network Song")
        with patch(
            "jl_mixing.api.project_create.resolve_client_reference",
            return_value=Path(r"\\server\mixes\Clients\Client"),
        ), patch(
            "jl_mixing.api.project_create.create_project",
            side_effect=OSError(5, "Access is denied"),
        ):
            payload, exit_code = execute(request)

        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["operation"], "project.create")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["errors"][0]["code"], "FILESYSTEM_ERROR")
        self.assertIn("Access is denied", payload["errors"][0]["message"])


if __name__ == "__main__":
    unittest.main()
