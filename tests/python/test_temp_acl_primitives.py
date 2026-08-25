from __future__ import annotations

import unittest
from pathlib import Path


class TempAclPrimitiveTests(unittest.TestCase):
    def test_python_persistent_transactions_do_not_use_tempfile_private_primitives(self):
        root = Path(__file__).resolve().parents[2]
        for relative in (
            "src/jl_mixing/delivery.py",
            "src/jl_mixing/revision.py",
            "src/jl_mixing/revision_description.py",
            "src/jl_mixing/studio.py",
            "src/jl_mixing/shell_config.py",
            "src/jl_mixing/macos_installer.py",
            "src/jl_mixing/managed_client_files.py",
        ):
            text = (root / relative).read_text(encoding="utf-8")
            self.assertNotIn("tempfile.mkdtemp", text, relative)
            self.assertNotIn("tempfile.mkstemp", text, relative)

    def test_shell_persistent_transactions_do_not_use_mktemp_beside_destination(self):
        root = Path(__file__).resolve().parents[2]
        for relative in ("lib/transaction.sh", "install.sh", "uninstall.sh"):
            text = (root / relative).read_text(encoding="utf-8")
            self.assertNotIn('mktemp -d "$parent/', text, relative)
            self.assertNotIn('mktemp -d "$prefix/', text, relative)


if __name__ == "__main__":
    unittest.main()
