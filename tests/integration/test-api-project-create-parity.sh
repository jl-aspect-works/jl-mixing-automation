#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
human="$tmp/Human Studio"
api="$tmp/API Studio"
"$ROOT/bin/new-studio" --root "$human" --name Human --engineer Jake --no-default-cd >/dev/null
"$ROOT/bin/new-studio" --root "$api" --name API --engineer Jake --no-default-cd >/dev/null
(cd "$human" && "$ROOT/bin/new-client" parity --name "Parity Client" --artist "Parity Artist" --no-cd >/dev/null)
(cd "$api" && "$ROOT/bin/new-client" parity --name "Parity Client" --artist "Parity Artist" --no-cd >/dev/null)
(cd "$human" && "$ROOT/bin/new-mix" "Parity Project" --client parity --artist "Parity Artist" --sample-rate 48000 --bit-depth 24 --file-format WAV --deliverables main_mix,stems --no-cd >/dev/null)
api_response="$tmp/project-create-success.json"
(cd "$api" && "$ROOT/bin/jl-mixing" project create "Parity Project" --json --client parity --artist "Parity Artist" --sample-rate 48000 --bit-depth 24 --file-format WAV --deliverables main_mix,stems >"$api_response")
python3 - "$human/Clients/Parity Client/Projects/Parity Project/00_Admin/project-manifest.json" "$api/Clients/Parity Client/Projects/Parity Project/00_Admin/project-manifest.json" "$human/Clients/Parity Client/Projects/Parity Project/00_Admin/client-profile-snapshot.json" "$api/Clients/Parity Client/Projects/Parity Project/00_Admin/client-profile-snapshot.json" <<'PY'
import json, sys
from pathlib import Path
pairs=[(sys.argv[1],sys.argv[2]),(sys.argv[3],sys.argv[4])]
for left,right in pairs:
    a=json.loads(Path(left).read_text()); b=json.loads(Path(right).read_text())
    for d in (a,b):
        metadata=d.get("metadata", {})
        metadata.pop("document_id", None)
        metadata.pop("created_at", None)
        metadata.pop("last_modified_at", None)
        d.get("client", {}).pop("client_document_id", None)
        d.get("source_client", {}).pop("client_document_id", None)
        for rev in d.get("revisions", []):
            rev.pop("revision_id", None)
            rev.pop("created_at", None)
    assert a == b, (a,b)
PY
pass "API and human commands create equivalent project state"

python3 - "$api_response" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["status"] == "success"
assert d["operation"] == "project.create"
assert d["errors"] == []
assert Path(d["data"]["manifest_path"]).is_file()
assert Path(d["data"]["client_snapshot_path"]).is_file()
assert Path(d["data"]["initial_revision_path"]).is_dir()
PY
pass "project.create success response points to committed state"

if python3 -c 'import jsonschema' >/dev/null 2>&1; then
    assert_success "project.create success matches schema" python3 "$ROOT/tools/validate-json.py" --strict \
        --schema "$ROOT/api/schemas/v1.0/operations/project-create.schema.json" --document "$api_response"
fi

human_project="$human/Clients/Parity Client/Projects/Parity Project"
api_project="$api/Clients/Parity Client/Projects/Parity Project"
"$ROOT/bin/new-revision" --project "$human_project" --description "Parity revision" --no-cd >/dev/null
revision_response="$tmp/revision-create-success.json"
"$ROOT/bin/jl-mixing" revision create --json --project "$api_project" --description "Parity revision" >"$revision_response"

python3 - "$human_project/00_Admin/project-manifest.json" "$api_project/00_Admin/project-manifest.json" <<'PY'
import json, sys
from pathlib import Path
a=json.loads(Path(sys.argv[1]).read_text()); b=json.loads(Path(sys.argv[2]).read_text())
for d in (a,b):
    metadata=d.get("metadata", {})
    metadata.pop("document_id", None)
    metadata.pop("created_at", None)
    metadata.pop("last_modified_at", None)
    d.get("client", {}).pop("client_document_id", None)
    for rev in d.get("revisions", []):
        rev.pop("revision_id", None)
        rev.pop("created_at", None)
assert a == b, (a,b)
PY
assert_eq "$(cat "$human_project/04_Revisions/Revision_02/Revision_Notes.md")" \
    "$(cat "$api_project/04_Revisions/Revision_02/Revision_Notes.md")" \
    "revision notes are equivalent"
pass "API and human commands create equivalent revision state"

python3 - "$revision_response" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["status"] == "success"
assert d["operation"] == "revision.create"
assert d["errors"] == []
assert d["data"]["revision"]["number"] == 2
assert Path(d["data"]["manifest_path"]).is_file()
assert Path(d["data"]["revision"]["path"]).is_dir()
assert Path(d["data"]["revision_notes_path"]).is_file()
PY
pass "revision.create success response points to committed state"

if python3 -c 'import jsonschema' >/dev/null 2>&1; then
    assert_success "revision.create success matches schema" python3 "$ROOT/tools/validate-json.py" --strict \
        --schema "$ROOT/api/schemas/v1.0/operations/revision-create.schema.json" --document "$revision_response"
fi

# Intake validation through the API must produce the same authoritative managed
# report content as the human command for equivalent source trees.
printf 'same notes\n' > "$human_project/01_Client_Files/Original_Delivery/Notes.txt"
printf 'same notes\n' > "$api_project/01_Client_Files/Original_Delivery/Notes.txt"
"$ROOT/bin/validate-intake" --project "$human_project" >/dev/null
intake_response="$tmp/intake-validate-success.json"
"$ROOT/bin/jl-mixing" intake validate --json --project "$api_project" >"$intake_response"
python3 - "$human_project/00_Admin/Intake_Report.md" "$api_project/00_Admin/Intake_Report.md" "$human_project" "$api_project" <<'PY'
from pathlib import Path
import sys
left=Path(sys.argv[1]).read_text(); right=Path(sys.argv[2]).read_text()
left=left.replace(sys.argv[3], "<PROJECT>")
right=right.replace(sys.argv[4], "<PROJECT>")
assert left == right, (left, right)
PY
pass "API and human intake validation produce equivalent reports"

python3 - "$intake_response" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["status"] == "success"
assert d["operation"] == "intake.validate"
assert d["errors"] == []
assert d["data"]["summary"]["files_discovered"] == 1
assert Path(d["data"]["intake_report_path"]).is_file()
PY
pass "intake.validate success response points to authoritative report"

if python3 -c 'import jsonschema' >/dev/null 2>&1; then
    assert_success "intake.validate success matches schema" python3 "$ROOT/tools/validate-json.py" --strict \
        --schema "$ROOT/api/schemas/v1.0/operations/intake-validate.schema.json" --document "$intake_response"
fi

# Approval through both surfaces must produce equivalent authoritative manifest
# state when the selected revision, approver, and timestamp are identical.
approval_date="2030-01-01T12:00:00Z"
"$ROOT/bin/approve-mix" --project "$human_project" --revision 2 --approved-by Client --date "$approval_date" >/dev/null
approval_response="$tmp/revision-approve-success.json"
"$ROOT/bin/jl-mixing" revision approve --json --project "$api_project" --revision 2 --approved-by Client --date "$approval_date" >"$approval_response"
python3 - "$human_project/00_Admin/project-manifest.json" "$api_project/00_Admin/project-manifest.json" <<'PY'
import json,sys
from pathlib import Path
a=json.loads(Path(sys.argv[1]).read_text()); b=json.loads(Path(sys.argv[2]).read_text())
for d in (a,b):
    metadata=d.get("metadata", {})
    metadata.pop("document_id", None)
    metadata.pop("created_at", None)
    metadata.pop("last_modified_at", None)
    d.get("client", {}).pop("client_document_id", None)
    for rev in d.get("revisions", []):
        rev.pop("revision_id", None)
        rev.pop("created_at", None)
assert a == b, (a,b)
PY
pass "API and human approval produce equivalent project state"

python3 - "$approval_response" "$approval_date" <<'PY'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["status"] == "success"
assert d["operation"] == "revision.approve"
assert d["errors"] == []
assert d["data"]["revision"]["number"] == 2
assert d["data"]["approved_by"] == "Client"
assert d["data"]["approved_at"] == sys.argv[2]
assert Path(d["data"]["manifest_path"]).is_file()
PY
pass "revision.approve success response points to committed approval state"

if python3 -c 'import jsonschema' >/dev/null 2>&1; then
    assert_success "revision.approve success matches schema" python3 "$ROOT/tools/validate-json.py" --strict \
        --schema "$ROOT/api/schemas/v1.0/operations/revision-approve.schema.json" --document "$approval_response"
fi

echo "[OK] Automation API project/revision/intake/approval parity ($TEST_COUNT assertions)"
