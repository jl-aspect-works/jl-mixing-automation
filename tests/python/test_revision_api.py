from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jl_mixing.project import ProjectCreateRequest, create_project

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def write_workspace(root: Path) -> tuple[Path, Path, Path]:
    (root / "Studio").mkdir(parents=True)
    (root / "Clients").mkdir()
    studio = {
        "metadata": {
            "schema": "mixing-studio", "schema_version": "1.1.0",
            "document_id": "11111111-1111-1111-1111-111111111111",
            "created_with": "jl-mixing 1.4.0", "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "studio_id": "api-studio", "studio_name": "API Studio", "root_path": str(root),
        "defaults": {
            "mix_engineer": "API Engineer",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
        "cli": {"change_directory_after_create": True},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    client = root / "Clients" / "API Client"
    (client / "Projects").mkdir(parents=True)
    client_doc = {
        "metadata": {
            "schema": "mixing-client", "schema_version": "1.1.0",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "created_with": "jl-mixing 1.4.0", "created_at": "2030-01-01T12:00:00Z",
            "last_modified_at": "2030-01-01T12:00:00Z",
        },
        "client_id": "api-client", "client_name": "API Client",
        "defaults": {
            "artist": "API Artist",
            "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
            "delivery": {"method": "Cloud", "requested_deliverables": ["main_mix"]},
        },
    }
    (client / "client.json").write_text(json.dumps(client_doc), encoding="utf-8")
    project = create_project(ProjectCreateRequest(client, "API Song", change_directory=False)).project_root
    return root, client, project


def run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-m", "jl_mixing.cli", *args],
        cwd=cwd, env=env, text=True, capture_output=True, check=False,
    )


class RevisionApiTests(unittest.TestCase):
    def test_dry_run_from_project_context_is_structured_and_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, project = write_workspace(Path(tmp))
            proc = run_cli(project, "revision", "create", "--json", "--dry-run")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stderr, "")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["operation"], "revision.create")
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["data"]["revision"]["number"], 2)
            self.assertEqual(payload["data"]["revision"]["description"], "Revision 2")
            self.assertEqual(len(payload["data"]["would_create"]), 2)
            self.assertEqual(payload["data"]["would_update"], [str((project / "00_Admin" / "project-manifest.json").resolve())])
            self.assertFalse((project / "04_Revisions" / "Revision_02").exists())

    def test_success_with_explicit_project_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _, project = write_workspace(Path(tmp))
            source = root / "mix.wav"
            source.write_bytes(b"mix")
            proc = run_cli(
                root,
                "revision", "create", "--project", str(project), "--description", "Client notes",
                "--source", str(source), "--json",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "success")
            self.assertEqual(payload["data"]["revision"]["number"], 2)
            self.assertEqual(payload["data"]["revision"]["description"], "Client notes")
            revision_path = Path(payload["data"]["revision"]["path"])
            self.assertEqual(revision_path, (project / "04_Revisions" / "Revision_02").resolve())
            self.assertEqual((revision_path / "mix.wav").read_bytes(), b"mix")
            manifest = json.loads((project / "00_Admin" / "project-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"]["current_revision"], 2)

    def test_missing_source_is_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, _, project = write_workspace(Path(tmp))
            proc = run_cli(project, "revision", "create", "--source", str(root / "missing.wav"), "--json")
            self.assertEqual(proc.returncode, 4)
            self.assertEqual(proc.stderr, "")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["errors"][0]["code"], "SOURCE_NOT_FOUND")

    def test_existing_revision_destination_is_classified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, project = write_workspace(Path(tmp))
            (project / "04_Revisions" / "Revision_02").mkdir()
            proc = run_cli(project, "revision", "create", "--json")
            self.assertIn(proc.returncode, {5, 6})
            self.assertEqual(proc.stderr, "")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["errors"][0]["code"], "REVISION_ALREADY_EXISTS")

    def test_json_mode_rejects_shell_cd_and_requires_exactly_one_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, _, project = write_workspace(Path(tmp))
            proc = run_cli(project, "revision", "create", "--json", "--cd")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(json.loads(proc.stdout)["errors"][0]["code"], "INVALID_REQUEST")
            proc = run_cli(project, "revision", "create")
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(json.loads(proc.stdout)["errors"][0]["code"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
