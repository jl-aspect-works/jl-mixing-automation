from __future__ import annotations

import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from jl_mixing.delivery import DeliveryCreateRequest, create_delivery
from jl_mixing.delivery_management import DeliveryStatusRequest, inspect_delivery
from jl_mixing.errors import ValidationError
from jl_mixing.managed_client_files import execute_plan, plan_import
from test_delivery_service import write_project


FILESYSTEM_NOISE = (
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "Stems/._bass.wav",
)


def managed_project(root: Path) -> Path:
    project = root / "project"
    (project / "00_Admin").mkdir(parents=True)
    (project / "01_Client_Files" / "Original_Delivery").mkdir(parents=True)
    (project / "02_Audio_Preparation" / "Working_Audio").mkdir(parents=True)
    return project


def write_regular_zip_entry(handle: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name)
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    handle.writestr(info, content)


class FilesystemNoiseTests(unittest.TestCase):
    def test_delivery_ignores_recreated_filesystem_metadata_without_staling_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            created = create_delivery(DeliveryCreateRequest(project, make_zip=True))
            self.assertIsNotNone(created.zip_name)
            delivery = project / "05_Final_Delivery"
            (delivery / ".DS_Store").write_bytes(b"finder")
            (delivery / "Thumbs.db").write_bytes(b"windows")
            (delivery / "desktop.ini").write_text("[ViewState]\n", encoding="utf-8")
            (delivery / "Stems" / "._bass.wav").write_bytes(b"appledouble")

            status = inspect_delivery(DeliveryStatusRequest(project))

            self.assertEqual(status["state"], "ready")
            self.assertEqual(status["untracked"], [])
            self.assertEqual(status["issues"], [])
            self.assertEqual(status["package_state"], "current")
            self.assertEqual(status["current_package"]["name"], created.zip_name)

            (delivery / "unexpected.txt").write_text("real user file\n", encoding="utf-8")
            status = inspect_delivery(DeliveryStatusRequest(project))
            self.assertEqual(status["state"], "needs_attention")
            self.assertEqual(status["untracked"], ["unexpected.txt"])
            self.assertIn("UNTRACKED_DELIVERY_FILE", {item["code"] for item in status["issues"]})

    def test_folder_import_excludes_nested_filesystem_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = managed_project(root)
            source = root / "source"
            (source / "Stems").mkdir(parents=True)
            (source / "mix.wav").write_bytes(b"mix")
            (source / "Stems" / "bass.wav").write_bytes(b"bass")
            (source / ".DS_Store").write_bytes(b"finder")
            (source / "Thumbs.db").write_bytes(b"windows")
            (source / "desktop.ini").write_bytes(b"windows")
            (source / "Stems" / "._bass.wav").write_bytes(b"appledouble")

            plan = plan_import(project, "folder", (source,))
            self.assertEqual([item["relative_path"] for item in plan["files"]], ["mix.wav", "Stems/bass.wav"])
            self.assertEqual(len(plan["items"]), 4)

            execute_plan(project, plan, {})
            original = project / "01_Client_Files" / "Original_Delivery"
            audio = project / "02_Audio_Preparation" / "Working_Audio"
            self.assertEqual((original / "mix.wav").read_bytes(), b"mix")
            self.assertEqual((original / "Stems" / "bass.wav").read_bytes(), b"bass")
            self.assertEqual((audio / "mix.wav").read_bytes(), b"mix")
            self.assertEqual((audio / "Stems" / "bass.wav").read_bytes(), b"bass")
            for relative in FILESYSTEM_NOISE:
                self.assertFalse((original / relative).exists())
                self.assertFalse((audio / relative).exists())

    def test_zip_and_direct_file_imports_exclude_filesystem_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = managed_project(root)
            archive = root / "delivery.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                write_regular_zip_entry(handle, "mix.wav", b"mix")
                write_regular_zip_entry(handle, ".DS_Store", b"finder")
                write_regular_zip_entry(handle, "Stems/Thumbs.db", b"windows")
                write_regular_zip_entry(handle, "Stems/._bass.wav", b"appledouble")

            zip_plan = plan_import(project, "zip", (archive,))
            self.assertEqual([item["relative_path"] for item in zip_plan["files"]], ["mix.wav"])

            mix = root / "direct.wav"
            mix.write_bytes(b"direct")
            noise = root / ".DS_Store"
            noise.write_bytes(b"finder")
            direct_plan = plan_import(project, "files", (noise, mix))
            self.assertEqual([item["relative_path"] for item in direct_plan["files"]], ["direct.wav"])

            with self.assertRaisesRegex(ValidationError, "Import source contains no files"):
                plan_import(project, "files", (noise,))


if __name__ == "__main__":
    unittest.main()
