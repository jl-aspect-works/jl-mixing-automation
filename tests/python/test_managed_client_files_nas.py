from __future__ import annotations

import errno
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jl_mixing.managed_client_files import execute_plan, plan_import


class ManagedClientFilesNasTests(unittest.TestCase):
    def test_import_does_not_require_filesystem_metadata_preservation(self):
        """SMB/NAS mounts may reject copystat even though content copies are valid."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "Project"
            (project / "00_Admin").mkdir(parents=True)
            (project / "01_Client_Files" / "Original_Delivery").mkdir(parents=True)
            (project / "02_Audio_Preparation" / "Working_Audio").mkdir(parents=True)
            source = root / "10_Piano.wav"
            source.write_bytes(b"audio-content")

            plan = plan_import(project, "files", (source,))

            with patch.object(
                shutil,
                "copystat",
                side_effect=OSError(errno.EINVAL, "NAS rejects metadata preservation"),
            ):
                result = execute_plan(project, plan, {})

            self.assertEqual([item["result"] for item in result["items"]], ["created", "created"])
            self.assertEqual(
                (project / "01_Client_Files" / "Original_Delivery" / source.name).read_bytes(),
                b"audio-content",
            )
            self.assertEqual(
                (project / "02_Audio_Preparation" / "Working_Audio" / source.name).read_bytes(),
                b"audio-content",
            )
            self.assertFalse(any((project / "00_Admin").glob(".jl-managed-import-*")))


if __name__ == "__main__":
    unittest.main()
