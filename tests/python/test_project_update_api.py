from __future__ import annotations

import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]; SRC=ROOT/'src'


def fixture(root: Path) -> Path:
    (root/'Studio').mkdir(parents=True); client=root/'Clients'/'Client'; project=client/'Projects'/'Stable Project'; (project/'00_Admin').mkdir(parents=True); (project/'01_Client_Files'/'Original_Delivery').mkdir(parents=True); (project/'02_Audio_Preparation'/'Working_Audio').mkdir(parents=True); (project/'05_Final_Delivery').mkdir(parents=True)
    studio={"metadata":{"schema":"mixing-studio","schema_version":"1.1.0","document_id":"44444444-4444-4444-4444-444444444444","created_with":"jl-mixing 2.0.0","created_at":"2030-01-01T12:00:00Z","last_modified_at":"2030-01-01T12:00:00Z"},"studio_id":"studio","studio_name":"Studio","root_path":str(root),"defaults":{"mix_engineer":"Engineer","audio":{"sample_rate":48000,"bit_depth":24,"file_format":"WAV"},"delivery":{"method":"Cloud transfer","requested_deliverables":["main_mix"]}},"cli":{"change_directory_after_create":False}}
    (root/'Studio'/'studio.json').write_text(json.dumps(studio))
    client_doc={"metadata":{"schema":"mixing-client","schema_version":"1.1.0","document_id":"55555555-5555-4555-8555-555555555555","created_with":"jl-mixing 2.0.0","created_at":"2030-01-01T12:00:00Z","last_modified_at":"2030-01-01T12:00:00Z"},"client_id":"client","client_name":"Client","defaults":{"artist":"Artist","audio":{"sample_rate":48000,"bit_depth":24,"file_format":"WAV"},"delivery":{"method":"Cloud transfer","requested_deliverables":["main_mix"]}}}
    (client/'client.json').write_text(json.dumps(client_doc))
    manifest={"metadata":{"schema":"mixing-project","schema_version":"1.1.0","document_id":"66666666-6666-4666-8666-666666666666","created_with":"jl-mixing 2.0.0","created_at":"2030-01-01T12:00:00Z","last_modified_at":"2030-01-01T12:00:00Z"},"project_id":"stable-project","project_name":"Original Project","client":{"client_document_id":client_doc['metadata']['document_id'],"client_id":"client"},"artist":"Artist","album":"","producer":"","mix_engineer":"Engineer","music":{"bpm":120,"key":"C","time_signature":"4/4"},"audio":{"sample_rate":48000,"bit_depth":24,"file_format":"WAV"},"delivery":{"method":"Cloud transfer","requested_deliverables":["main_mix"]},"schedule":{"deadline":None},"creative_direction":"Original","state":{"current_revision":1,"approved_revision":None,"delivered_revision":None},"revisions":[{"number":1,"revision_id":"77777777-7777-4777-8777-777777777777","created_at":"2030-01-01T12:00:00Z","description":"Initial revision","approval":{"approved_at":None,"approved_by":None}}]}
    (project/'00_Admin'/'project-manifest.json').write_text(json.dumps(manifest)); return project


def run(cwd:Path,*args:str,fail_at:str|None=None):
    env=os.environ.copy(); env['PYTHONPATH']=str(SRC)
    if fail_at: env['JL_MIXING_FAIL_AT']=fail_at
    return subprocess.run([sys.executable,'-m','jl_mixing.cli',*args],cwd=cwd,env=env,text=True,capture_output=True,check=False)


class ProjectUpdateApiTests(unittest.TestCase):
    def test_updates_allowlist_preserves_identity_state_and_reports_invalidations(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=fixture(Path(tmp)); path=project/'00_Admin'/'project-manifest.json'; before=json.loads(path.read_text()); revisions=json.dumps(before['revisions'],sort_keys=True); state=json.dumps(before['state'],sort_keys=True); client=json.dumps(before['client'],sort_keys=True)
            p=run(project,'project','update','--json','--name','Renamed','--artist','New Artist','--album','Album','--producer','Producer','--engineer','New Engineer','--bpm','128.5','--key','D','--time-signature','3/4','--sample-rate','96000','--bit-depth','32','--file-format','aiff','--delivery-method','Secure upload','--deliverables','main_mix,stems','--deadline','2030-12-31','--creative-direction','Updated')
            self.assertEqual(p.returncode,0,p.stderr); payload=json.loads(p.stdout); self.assertEqual(payload['status'],'success'); self.assertEqual(payload['data']['invalidations'],['intake.validation_context','audio_prep.validation_context','delivery.readiness'])
            after=json.loads(path.read_text()); self.assertEqual(after['project_id'],before['project_id']); self.assertEqual(json.dumps(after['client'],sort_keys=True),client); self.assertEqual(json.dumps(after['state'],sort_keys=True),state); self.assertEqual(json.dumps(after['revisions'],sort_keys=True),revisions); self.assertEqual(project.name,'Stable Project'); self.assertEqual(after['audio'],{'sample_rate':96000,'bit_depth':32,'file_format':'AIFF'}); self.assertEqual(after['schedule']['deadline'],'2030-12-31')
    def test_dry_run_clear_values_invalid_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=fixture(Path(tmp)); path=project/'00_Admin'/'project-manifest.json'; original=path.read_bytes()
            p=run(project,'project','update','--json','--bpm','null','--deadline','null','--sample-rate','96000','--dry-run'); self.assertEqual(p.returncode,0,p.stderr); data=json.loads(p.stdout)['data']; self.assertIn('intake.validation_context',data['invalidations']); self.assertEqual(path.read_bytes(),original)
            p=run(project,'project','update','--json','--artist',''); self.assertEqual(p.returncode,5); self.assertEqual(path.read_bytes(),original)
            p=run(project,'project','update','--json','--name','Rollback',fail_at='after-file-replacement'); self.assertNotEqual(p.returncode,0); self.assertEqual(path.read_bytes(),original)


if __name__=='__main__': unittest.main()
