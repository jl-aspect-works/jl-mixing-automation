from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from jl_mixing.system_info import document


class SystemInfoTests(unittest.TestCase):
    def test_document_preserves_v14_contract_with_additive_capabilities(self) -> None:
        info = document()
        self.assertEqual(info["api_version"], "1.0")
        self.assertEqual(info["application"]["name"], "jl-mixing")
        self.assertEqual(info["application"]["version"], (ROOT / "VERSION").read_text().strip())
        self.assertEqual(info["metadata"], {"readable_schema_versions": ["1.1.0"], "writable_schema_version": "1.1.0"})
        self.assertEqual(info["capabilities"], [
            "audio.prep.provenance.sha256", "audio.prep.reset.execute", "audio.prep.reset.plan",
            "audio.prep.validation.structured", "client.create", "client.create.context", "client.update",
            "client.files.import.execute", "client.files.import.plan", "delivery.create",
            "delivery.package.delete", "delivery.package.rebuild", "delivery.status", "intake.validate",
            "intake.validate.incremental", "intake.validate.report", "intake.validate.structured",
            "project.create", "project.create.artist", "project.update", "revision.approve", "revision.close",
            "revision.create", "revision.create.description", "revision.reopen", "revision.unapprove",
            "revision.update.description", "studio.update", "system.info",
        ])
        self.assertEqual(Path(info["schemas"]["installed_path"]), (ROOT / "api" / "schemas" / "v1.0").resolve())

    def test_cli_emits_machine_json(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC)
        proc = subprocess.run([sys.executable, "-m", "jl_mixing.cli", "system-info", "--json"], cwd=ROOT, env=env, text=True, capture_output=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        self.assertEqual(json.loads(proc.stdout), document())


if __name__ == "__main__":
    unittest.main()
