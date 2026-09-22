from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from jl_mixing.context import client_root, project_root, resolve_project, revision_root_for_number, studio_root
from jl_mixing.errors import ContextError, UnsafeOperationError, ValidationError
from jl_mixing.paths import (
    assert_automation_owned_path,
    assert_no_case_insensitive_child_collision,
    assert_no_symlink_components,
    portable_relative_path,
    resolve_under_root,
)
from jl_mixing.transactions import atomic_write_text


def write_record(path: Path, schema: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "metadata": {
                    "schema": schema,
                    "schema_version": "1.1.0",
                    "created_with": "jl-mixing 1.4.0",
                }
            }
        ),
        encoding="utf-8",
    )


class PortablePathTests(unittest.TestCase):
    def test_manifest_paths_remain_forward_slash_portable(self) -> None:
        self.assertEqual(str(portable_relative_path("Stems/Drums.wav")), "Stems/Drums.wav")
        for invalid in ("", "/absolute", "../escape", "a//b", "a/./b", r"a\b"):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                portable_relative_path(invalid)

    def test_resolve_under_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertEqual(resolve_under_root(root, "A/B.wav"), root / "A" / "B.wav")

    def test_case_insensitive_collision_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Client").mkdir()
            with self.assertRaises(ValidationError):
                assert_no_case_insensitive_child_collision(root, "client")

    def test_user_owned_boundaries_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "Project"
            for path in (
                project / "01_Client_Files" / "Original_Delivery" / "source.wav",
                project / "03_DAW_Project" / "session.logicx",
            ):
                with self.subTest(path=path), self.assertRaises(UnsafeOperationError):
                    assert_automation_owned_path(path)

    @unittest.skipIf(os.name == "nt", "Windows symlink creation may require elevated developer settings")
    def test_symlink_component_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            outside = Path(tmp) / "outside"
            root.mkdir(); outside.mkdir()
            (root / "link").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(UnsafeOperationError):
                assert_no_symlink_components(root, root / "link" / "file.txt")


class ContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "Studio Root"
        self.client = self.root / "Clients" / "API Client"
        self.project = self.client / "Projects" / "Blue Sky"
        self.revision = self.project / "04_Revisions" / "Revision_01"
        self.revision.mkdir(parents=True)
        write_record(self.root / "Studio" / "studio.json", "mixing-studio")
        write_record(self.client / "client.json", "mixing-client")
        write_record(self.project / "00_Admin" / "project-manifest.json", "mixing-project")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_upward_discovery_matches_workspace_boundaries(self) -> None:
        leaf = self.revision / "nested" / "file.wav"
        self.assertEqual(project_root(leaf), self.project.resolve())
        self.assertEqual(client_root(leaf), self.client.resolve())
        self.assertEqual(studio_root(leaf), self.root.resolve())

    def test_explicit_manifest_path_resolves_project(self) -> None:
        manifest = self.project / "00_Admin" / "project-manifest.json"
        self.assertEqual(resolve_project(manifest, self.root), self.project.resolve())

    def test_revision_number_uses_flattened_canonical_layout(self) -> None:
        self.assertEqual(revision_root_for_number(self.project, 1), self.revision)
        with self.assertRaises(ContextError):
            revision_root_for_number(self.project, 2)


class TransactionTests(unittest.TestCase):
    def test_atomic_write_replaces_content_without_temp_leak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            target.write_text("old\n", encoding="utf-8")
            atomic_write_text(target, "new\r\n")
            self.assertEqual(target.read_bytes(), b"new\n")
            self.assertEqual([p.name for p in target.parent.iterdir()], ["state.json"])

    def test_atomic_write_rejects_original_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "01_Client_Files" / "Original_Delivery" / "state.txt"
            with self.assertRaises(UnsafeOperationError):
                atomic_write_text(target, "unsafe")


if __name__ == "__main__":
    unittest.main()
