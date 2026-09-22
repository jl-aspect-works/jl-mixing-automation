from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jl_mixing.delivery import DeliveryCreateRequest, create_delivery
from jl_mixing.delivery_management import (
    DeliveryDeletePackageRequest,
    DeliveryStatusRequest,
    delete_generated_package,
    inspect_delivery,
)
from jl_mixing.errors import ContextError, UnsafeOperationError
from test_delivery_service import write_project


class DeliveryManagementTests(unittest.TestCase):
    def test_status_reports_current_manifest_deliverables_and_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            created = create_delivery(DeliveryCreateRequest(project, make_zip=True))
            status = inspect_delivery(DeliveryStatusRequest(project))

            self.assertEqual(status["state"], "ready")
            self.assertEqual(status["revisions"]["source"], 1)
            self.assertEqual(status["revisions"]["approved"], 1)
            self.assertEqual(status["deliverable_count"], 3)
            self.assertTrue(all(item["status"] == "current" for item in status["deliverables"]))
            self.assertEqual(status["untracked"], [])
            self.assertEqual(status["issues"], [])
            self.assertEqual(status["package_state"], "current")
            self.assertEqual(status["current_package"]["name"], created.zip_name)

    def test_status_detects_hash_mismatch_and_untracked_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            create_delivery(DeliveryCreateRequest(project))
            delivery = project / "05_Final_Delivery"
            (delivery / "Delivery Song Main Mix.wav").write_bytes(b"changed-outside-automation")
            (delivery / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")

            status = inspect_delivery(DeliveryStatusRequest(project))
            by_path = {item["path"]: item for item in status["deliverables"]}
            codes = {item["code"] for item in status["issues"]}

            self.assertEqual(status["state"], "needs_attention")
            self.assertEqual(by_path["Delivery Song Main Mix.wav"]["status"], "mismatch")
            self.assertIn("unexpected.txt", status["untracked"])
            self.assertIn("DELIVERABLE_HASH_MISMATCH", codes)
            self.assertIn("UNTRACKED_DELIVERY_FILE", codes)

    def test_delivery_notes_edit_marks_existing_package_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            create_delivery(DeliveryCreateRequest(project, make_zip=True))
            delivery = project / "05_Final_Delivery"
            (delivery / "Delivery_Notes.md").write_text("Changed after package build\n", encoding="utf-8")

            status = inspect_delivery(DeliveryStatusRequest(project))

            self.assertEqual(status["state"], "ready")
            self.assertEqual(status["package_state"], "stale")
            self.assertEqual(status["packages"][0]["status"], "stale")
            package_codes = {item["code"] for item in status["packages"][0]["issues"]}
            self.assertIn("PACKAGE_STALE_FILE", package_codes)

    def test_delete_package_removes_only_generated_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            created = create_delivery(DeliveryCreateRequest(project, make_zip=True))
            self.assertIsNotNone(created.zip_name)
            delivery = project / "05_Final_Delivery"
            archive = delivery / str(created.zip_name)
            self.assertTrue(archive.is_file())

            result = delete_generated_package(DeliveryDeletePackageRequest(project, str(created.zip_name)))

            self.assertFalse(archive.exists())
            self.assertEqual(result["deleted_name"], created.zip_name)
            self.assertEqual(result["delivery"]["package_state"], "none")
            with self.assertRaises(UnsafeOperationError):
                delete_generated_package(DeliveryDeletePackageRequest(project, "Delivery Song Main Mix.wav"))

    def test_failed_package_delete_preserves_existing_delivery_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = write_project(Path(tmp))
            created = create_delivery(DeliveryCreateRequest(project, make_zip=True))
            self.assertIsNotNone(created.zip_name)
            delivery = project / "05_Final_Delivery"
            archive = delivery / str(created.zip_name)
            manifest = delivery / "delivery-manifest.json"
            manifest_before = manifest.read_bytes()
            status_before = inspect_delivery(DeliveryStatusRequest(project))
            self.assertEqual(status_before["state"], "ready")
            self.assertEqual(status_before["package_state"], "current")

            with patch.object(Path, "unlink", side_effect=OSError("simulated package delete failure")):
                with self.assertRaises(ContextError):
                    delete_generated_package(DeliveryDeletePackageRequest(project, str(created.zip_name)))

            self.assertTrue(archive.is_file())
            self.assertEqual(manifest.read_bytes(), manifest_before)
            status_after = inspect_delivery(DeliveryStatusRequest(project))
            self.assertEqual(status_after["state"], "ready")
            self.assertEqual(status_after["package_state"], "current")
            self.assertEqual(status_after["current_package"]["name"], created.zip_name)


if __name__ == "__main__":
    unittest.main()
