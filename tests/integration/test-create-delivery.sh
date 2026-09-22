#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/integration/integration-helper.sh"
require_test_command jq
require_test_command python3
python3 -c 'import jsonschema' >/dev/null 2>&1 || { echo '[SKIP] create-delivery requires jsonschema.'; exit 0; }

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
studio_root="$tmp/studio"
project_root="$(fixture_v11_approved_project "$studio_root")"
manifest="$project_root/00_Admin/project-manifest.json"
revision="$project_root/04_Revisions/Revision_01"
printf 'main-data\n' > "$revision/Blue Sky Main Mix.wav"
printf 'custom-data\n' > "$revision/BlueSky_NoVox.wav"
printf 'stem-data\n' > "$revision/Blue Sky Stem Drums.wav"
printf 'working\n' > "$revision/WORK Blue Sky test.wav"

delivery="$project_root/05_Final_Delivery"
dm="$delivery/delivery-manifest.json"
# GitHub macOS runners may place a newer Bash ahead of Apple's /bin/bash in
# PATH. Exercise the public command with the system Bash on macOS so Bash 3.2
# compatibility regressions are caught by CI.
delivery_command=("$ROOT/bin/create-delivery")
if [ "$(uname -s)" = "Darwin" ] && [ -x /bin/bash ]; then
    delivery_command=(/bin/bash "$ROOT/bin/create-delivery")
fi
run_delivery() { (cd "$project_root" && "${delivery_command[@]}" "$@"); }

dry="$(run_delivery --dry-run)"
assert_contains "$dry" 'Blue Sky Main Mix.wav' 'dry-run lists main mix'
assert_contains "$dry" 'BlueSky_NoVox.wav' 'dry-run lists custom file'
assert_contains "$dry" 'unclassified' 'dry-run shows unclassified type'
assert_path_not_exists "$dm"

output="$(run_delivery)"
assert_file_exists "$delivery/Blue Sky Main Mix.wav"
assert_file_exists "$delivery/BlueSky_NoVox.wav"
assert_file_exists "$delivery/Stems/Blue Sky Stem Drums.wav"
assert_path_not_exists "$delivery/WORK Blue Sky test.wav"
assert_file_exists "$dm"
assert_json_eq '1' "$manifest" '.state.delivered_revision' 'delivered pointer updated'
assert_json_eq 'mixing-delivery' "$dm" '.metadata.schema' 'delivery schema identity'
assert_json_eq 'main_mix' "$dm" '.files[] | select(.path=="Blue Sky Main Mix.wav") | .deliverable_type' 'main mix classified'
assert_json_eq 'unclassified' "$dm" '.files[] | select(.path=="BlueSky_NoVox.wav") | .deliverable_type' 'custom name unclassified'
assert_json_eq 'stems' "$dm" '.files[] | select(.path=="Stems/Blue Sky Stem Drums.wav") | .deliverable_type' 'stem classified'
assert_eq '64' "$(jq -r '.files[0].sha256 | length' "$dm")" 'mandatory SHA-256 stored'
assert_contains "$output" 'Final delivery created successfully.' 'success heading'
assert_contains "$output" 'Transfer the contents' 'transfer guidance'

assert_failure 'removed revision option rejected' run_delivery --revision 1
assert_failure 'removed checksum option rejected' run_delivery --checksum
assert_failure 'removed mark option rejected' run_delivery --mark-delivered
assert_failure 'removed non-interactive option rejected' run_delivery --non-interactive
assert_failure 'overwrite and clean are exclusive' run_delivery --overwrite --clean

# API parity: equivalent approved project state must produce the same delivery
# file set and equivalent manifest semantics through the machine dispatcher.
api_studio="$tmp/api-studio"
api_project="$(fixture_v11_approved_project "$api_studio")"
api_manifest="$api_project/00_Admin/project-manifest.json"
api_revision="$api_project/04_Revisions/Revision_01"
printf 'main-data\n' > "$api_revision/Blue Sky Main Mix.wav"
printf 'custom-data\n' > "$api_revision/BlueSky_NoVox.wav"
printf 'stem-data\n' > "$api_revision/Blue Sky Stem Drums.wav"
printf 'working\n' > "$api_revision/WORK Blue Sky test.wav"
api_delivery="$api_project/05_Final_Delivery"
api_dm="$api_delivery/delivery-manifest.json"
api_plan="$tmp/delivery-planned.json"
"$ROOT/bin/jl-mixing" delivery create --json --project "$api_project" --dry-run >"$api_plan"
assert_path_not_exists "$api_dm"
python3 - "$api_plan" "$api_project" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d['operation']=='delivery.create'
assert d['status']=='planned'
data=d['data']
assert data['project']['path']==sys.argv[2]
assert data['project']['name']=='Blue Sky'
assert data['revision']['number']==1
assert data['current_revision']==1
assert data['approved_revision']==1
assert data['delivered_revision'] is None
assert data['delivery_method']=='Cloud transfer'
assert data['replacement_mode']=='default'
assert data['zip_requested'] is False
assert data['zip_name'] is None
assert data['files_delivered']==0
assert [item['source_name'] for item in data['selected']]==[
    'Blue Sky Main Mix.wav','Blue Sky Stem Drums.wav','BlueSky_NoVox.wav'
]
assert [item['path'] for item in data['selected']]==[
    'Blue Sky Main Mix.wav','Stems/Blue Sky Stem Drums.wav','BlueSky_NoVox.wav'
]
assert any(item['name']=='Revision_Notes.md' for item in data['excluded'])
assert any(item['name']=='WORK Blue Sky test.wav' for item in data['excluded'])
assert data['deletions']==[]
PY
pass 'delivery.create dry-run exposes authoritative structured plan'

api_response="$tmp/delivery-success.json"
"$ROOT/bin/jl-mixing" delivery create --json --project "$api_project" >"$api_response"
assert_file_exists "$api_dm"
assert_json_eq '1' "$api_manifest" '.state.delivered_revision' 'API delivered pointer updated'
python3 - "$api_response" "$api_dm" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d['status']=='success'
assert d['errors']==[]
data=d['data']
assert data['revision']['number']==1
assert data['current_revision']==1
assert data['approved_revision']==1
assert data['delivered_revision']==1
assert Path(data['delivery_manifest_path'])==Path(sys.argv[2])
assert data['files_delivered']==3
assert len(data['selected'])==3
assert data['deletions']==[]
PY
pass 'delivery.create returns structured committed state'

python3 - "$dm" "$api_dm" <<'PY'
import json, sys
from pathlib import Path
a=json.loads(Path(sys.argv[1]).read_text()); b=json.loads(Path(sys.argv[2]).read_text())
for d in (a,b):
    d['metadata'].pop('document_id',None)
    d['metadata'].pop('created_at',None)
    d['metadata'].pop('created_with',None)
    d['project'].pop('project_document_id',None)
    d['client'].pop('client_document_id',None)
assert a==b,(a,b)
PY
assert_eq "$(cat "$delivery/Blue Sky Main Mix.wav")" "$(cat "$api_delivery/Blue Sky Main Mix.wav")" 'main mix content parity'
assert_eq "$(cat "$delivery/BlueSky_NoVox.wav")" "$(cat "$api_delivery/BlueSky_NoVox.wav")" 'custom file content parity'
assert_eq "$(cat "$delivery/Stems/Blue Sky Stem Drums.wav")" "$(cat "$api_delivery/Stems/Blue Sky Stem Drums.wav")" 'stem content parity'
pass 'API and human delivery creation produce equivalent authoritative state'

# Clean-mode preview must expose the exact destructive inventory so consumers
# can require confirmation without reconstructing or scraping human output.
clean_studio="$tmp/clean-studio"
clean_project="$(fixture_v11_approved_project "$clean_studio")"
clean_revision="$clean_project/04_Revisions/Revision_01"
printf 'main-data\n' > "$clean_revision/Blue Sky Main Mix.wav"
printf 'stale\n' > "$clean_project/05_Final_Delivery/stale-file.txt"
clean_plan="$tmp/delivery-clean-planned.json"
"$ROOT/bin/jl-mixing" delivery create --json --project "$clean_project" --clean --dry-run >"$clean_plan"
python3 - "$clean_plan" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
data=d['data']
assert d['status']=='planned'
assert data['replacement_mode']=='clean'
assert 'stale-file.txt' in data['deletions']
assert 'Delivery_Notes.md' in data['deletions']
PY
pass 'delivery.create clean preview exposes exact deletion inventory'

if python3 -c 'import jsonschema' >/dev/null 2>&1; then
    assert_success 'delivery.create planned response matches schema' python3 "$ROOT/tools/validate-json.py" --strict \
        --schema "$ROOT/api/schemas/v1.0/operations/delivery-create.schema.json" --document "$api_plan"
    assert_success 'delivery.create success response matches schema' python3 "$ROOT/tools/validate-json.py" --strict \
        --schema "$ROOT/api/schemas/v1.0/operations/delivery-create.schema.json" --document "$api_response"
    assert_success 'delivery.create clean planned response matches schema' python3 "$ROOT/tools/validate-json.py" --strict \
        --schema "$ROOT/api/schemas/v1.0/operations/delivery-create.schema.json" --document "$clean_plan"
fi

set +e
"$ROOT/bin/jl-mixing" delivery create --json --project "$api_project" >"$tmp/delivery-blocked.json" 2>"$tmp/delivery-blocked.err"
api_blocked_status=$?
set -e
assert_eq '5' "$api_blocked_status" 'existing delivery preserves validation exit code'
assert_eq '' "$(cat "$tmp/delivery-blocked.err")" 'blocked delivery keeps stderr empty'
python3 - "$tmp/delivery-blocked.json" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d['status']=='blocked'
assert d['errors'][0]['code']=='DELIVERY_REPLACEMENT_REQUIRED'
PY
pass 'delivery.create exposes replacement requirement'

echo "[OK] create-delivery ($TEST_COUNT assertions)"
