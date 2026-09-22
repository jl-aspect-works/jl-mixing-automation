from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def fixture(root: Path) -> tuple[Path, Path]:
    (root / "Studio").mkdir(parents=True)
    client = root / "Clients" / "Stable Folder"
    project = client / "Projects" / "Existing Project" / "00_Admin"
    project.mkdir(parents=True)
    studio = {
        "metadata": {"schema":"mixing-studio","schema_version":"1.1.0","document_id":"44444444-4444-4444-4444-444444444444","created_with":"jl-mixing 2.0.0","created_at":"2030-01-01T12:00:00Z","last_modified_at":"2030-01-01T12:00:00Z"},
        "studio_id":"api-studio","studio_name":"API Studio","root_path":str(root),
        "defaults":{"mix_engineer":"Engineer","audio":{"sample_rate":48000,"bit_depth":24,"file_format":"WAV"},"delivery":{"method":"Cloud transfer","requested_deliverables":["main_mix","instrumental"]}},
        "cli":{"change_directory_after_create":False},
    }
    (root / "Studio" / "studio.json").write_text(json.dumps(studio), encoding="utf-8")
    client_doc = {
        "metadata":{"schema":"mixing-client","schema_version":"1.1.0","document_id":"55555555-5555-4555-8555-555555555555","created_with":"jl-mixing 2.0.0","created_at":"2030-01-01T12:00:00Z","last_modified_at":"2030-01-01T12:00:00Z"},
        "client_id":"stable-client","client_name":"Original Client",
        "defaults":{"artist":"Original Artist","audio":{"sample_rate":48000,"bit_depth":24,"file_format":"WAV"},"delivery":{"method":"Cloud transfer","requested_deliverables":["main_mix","instrumental"]}},
    }
    (client / "client.json").write_text(json.dumps(client_doc), encoding="utf-8")
    project_file = project / "project-manifest.json"
    project_file.write_text('{"sentinel":"unchanged"}\n', encoding="utf-8")
    return client, project_file


def run(cwd: Path, *args: str, fail_at: str | None = None) -> subprocess.CompletedProcess[str]:
    env=os.environ.copy(); env["PYTHONPATH"]=str(SRC)
    if fail_at: env["JL_MIXING_FAIL_AT"]=fail_at
    return subprocess.run([sys.executable,"-m","jl_mixing.cli",*args],cwd=cwd,env=env,text=True,capture_output=True,check=False)


class ClientUpdateApiTests(unittest.TestCase):
    def test_success_preserves_identity_folder_and_existing_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio=Path(tmp); client, project=fixture(studio); before_project=project.read_bytes(); before=json.loads((client/'client.json').read_text())
            proc=run(studio,"client","update","--client","stable-client","--json","--name","Renamed Client","--artist","New Artist","--sample-rate","96000","--bit-depth","32","--file-format","aiff","--delivery-method","Secure upload","--deliverables","main_mix,stems")
            self.assertEqual(proc.returncode,0,proc.stderr); payload=json.loads(proc.stdout); self.assertEqual(payload["status"],"success")
            after=json.loads((client/'client.json').read_text())
            self.assertEqual(after["client_id"],before["client_id"]); self.assertEqual(client.name,"Stable Folder")
            for key in ("schema","schema_version","document_id","created_with","created_at"): self.assertEqual(after["metadata"][key],before["metadata"][key])
            self.assertNotEqual(after["metadata"]["last_modified_at"],before["metadata"]["last_modified_at"])
            self.assertEqual(after["client_name"],"Renamed Client"); self.assertEqual(after["defaults"]["artist"],"New Artist")
            self.assertEqual(after["defaults"]["audio"],{"sample_rate":96000,"bit_depth":32,"file_format":"AIFF"})
            self.assertEqual(project.read_bytes(),before_project)

    def test_dry_run_and_failures_preserve_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            studio=Path(tmp); client,_=fixture(studio); path=client/'client.json'; original=path.read_bytes()
            planned=run(client,"client","update","--json","--name","Planned","--dry-run")
            self.assertEqual(planned.returncode,0,planned.stderr); self.assertEqual(json.loads(planned.stdout)["status"],"planned"); self.assertEqual(path.read_bytes(),original)
            invalid=run(client,"client","update","--json","--sample-rate","12345")
            self.assertEqual(invalid.returncode,5); self.assertEqual(json.loads(invalid.stdout)["errors"][0]["code"],"VALIDATION_FAILED"); self.assertEqual(path.read_bytes(),original)
            failed=run(client,"client","update","--json","--name","Rollback",fail_at="after-file-replacement")
            self.assertNotEqual(failed.returncode,0); self.assertEqual(path.read_bytes(),original)


if __name__ == "__main__": unittest.main()
