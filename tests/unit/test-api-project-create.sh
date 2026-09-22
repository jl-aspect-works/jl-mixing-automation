#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
require_test_command python3

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
studio="$tmp/Studio Root"
"$ROOT/bin/new-studio" --root "$studio" --name "API Test Studio" --engineer "Jake" --no-default-cd >/dev/null
(cd "$studio" && "$ROOT/bin/new-client" api-client --name "API Client" --artist "API Artist" --no-cd >/dev/null)

planned="$tmp/planned.json"
(cd "$studio" && "$ROOT/bin/jl-mixing" project create "API Project" --json --client api-client --dry-run >"$planned")
assert_path_not_exists "$studio/Clients/API Client/Projects/API Project"
python3 - "$planned" "$studio" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["api_version"] == "1.0"
assert d["operation"] == "project.create"
assert d["status"] == "planned"
assert d["errors"] == [] and d["warnings"] == []
assert d["data"]["project"]["name"] == "API Project"
assert Path(d["data"]["workspace_path"]) == Path(sys.argv[2])
assert d["data"]["initial_revision_path"].endswith("Revision_01")
PY
pass "project.create dry-run is structured and non-mutating"

set +e
"$ROOT/bin/jl-mixing" project create >"$tmp/invalid.json" 2>"$tmp/invalid.err"
status=$?
set -e
assert_eq "2" "$status" "invalid project request preserves argument exit code"
assert_eq "" "$(cat "$tmp/invalid.err")" "API preflight failures keep stderr empty"
python3 - "$tmp/invalid.json" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["status"] == "error"
assert d["errors"][0]["code"] == "INVALID_REQUEST"
PY
pass "project.create invalid request is structured"

if python3 -c 'import jsonschema' >/dev/null 2>&1; then
    for document in "$planned" "$tmp/invalid.json"; do
        assert_success "project.create response matches schema" python3 "$ROOT/tools/validate-json.py" --strict \
            --schema "$ROOT/api/schemas/v1.0/operations/project-create.schema.json" --document "$document"
    done
else
    echo "[SKIP] project.create schema validation requires jsonschema."
fi

# revision.create planning uses an existing project and must not mutate it.
(cd "$studio" && "$ROOT/bin/new-mix" "Revision API Project" --client api-client --artist "API Artist" --no-cd >/dev/null)
project="$studio/Clients/API Client/Projects/Revision API Project"
revision_planned="$tmp/revision-planned.json"
"$ROOT/bin/jl-mixing" revision create --json --project "$project" --description "API revision" --dry-run >"$revision_planned"
assert_path_not_exists "$project/04_Revisions/Revision_02"
python3 - "$revision_planned" "$project" "$studio" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["api_version"] == "1.0"
assert d["operation"] == "revision.create"
assert d["status"] == "planned"
assert d["errors"] == [] and d["warnings"] == []
assert d["data"]["revision"]["number"] == 2
assert Path(d["data"]["project"]["path"]) == Path(sys.argv[2])
assert Path(d["data"]["workspace_path"]) == Path(sys.argv[3])
PY
pass "revision.create dry-run is structured and non-mutating"

set +e
"$ROOT/bin/jl-mixing" revision create --project "$project" >"$tmp/revision-invalid.json" 2>"$tmp/revision-invalid.err"
revision_status=$?
set -e
assert_eq "2" "$revision_status" "revision.create requires JSON mode"
assert_eq "" "$(cat "$tmp/revision-invalid.err")" "revision API preflight failures keep stderr empty"
python3 - "$tmp/revision-invalid.json" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["status"] == "error"
assert d["errors"][0]["code"] == "INVALID_REQUEST"
PY
pass "revision.create invalid request is structured"

if python3 -c 'import jsonschema' >/dev/null 2>&1; then
    for document in "$revision_planned" "$tmp/revision-invalid.json"; do
        assert_success "revision.create response matches schema" python3 "$ROOT/tools/validate-json.py" --strict \
            --schema "$ROOT/api/schemas/v1.0/operations/revision-create.schema.json" --document "$document"
    done
fi

# intake.validate must preserve report-only behavior while returning structured results.
(cd "$studio" && "$ROOT/bin/new-mix" "Intake API Project" --client api-client --artist "API Artist" --no-cd >/dev/null)
intake_project="$studio/Clients/API Client/Projects/Intake API Project"
printf 'session notes\n' > "$intake_project/01_Client_Files/Original_Delivery/Notes.txt"
intake_report="$intake_project/00_Admin/Intake_Report.md"
intake_before="$(cksum "$intake_report")"
intake_planned="$tmp/intake-planned.json"
"$ROOT/bin/jl-mixing" intake validate --json --project "$intake_project" --dry-run >"$intake_planned"
assert_eq "$intake_before" "$(cksum "$intake_report")" "intake.validate dry-run does not update report"
python3 - "$intake_planned" "$intake_project" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["operation"] == "intake.validate"
assert d["status"] == "planned"
assert d["data"]["project"]["path"] == sys.argv[2]
assert d["data"]["summary"]["files_discovered"] == 1
assert d["data"]["summary"]["blocking_errors"] == 0
PY
pass "intake.validate dry-run is structured and non-mutating"

intake_success="$tmp/intake-success.json"
"$ROOT/bin/jl-mixing" intake validate --json --project "$intake_project" >"$intake_success"
assert_contains "$(cat "$intake_report")" "Notes.txt" "intake.validate updates managed report"
python3 - "$intake_success" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["status"] == "success"
assert d["errors"] == []
assert d["data"]["summary"]["files_discovered"] == 1
assert d["data"]["summary"]["blocking_errors"] == 0
PY
pass "intake.validate returns structured success"

(cd "$studio" && "$ROOT/bin/new-mix" "Blocked Intake Project" --client api-client --artist "API Artist" --no-cd >/dev/null)
blocked_project="$studio/Clients/API Client/Projects/Blocked Intake Project"
set +e
"$ROOT/bin/jl-mixing" intake validate --json --project "$blocked_project" >"$tmp/intake-blocked.json" 2>"$tmp/intake-blocked.err"
intake_status=$?
set -e
assert_eq "5" "$intake_status" "blocking intake findings preserve validation exit code"
assert_eq "" "$(cat "$tmp/intake-blocked.err")" "completed blocked intake keeps stderr empty"
python3 - "$tmp/intake-blocked.json" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["status"] == "blocked"
assert d["data"]["summary"]["blocking_errors"] == 1
assert d["errors"][0]["code"] == "INTAKE_BLOCKING_FINDINGS"
PY
pass "intake.validate exposes blocking findings"

set +e
"$ROOT/bin/jl-mixing" intake validate --json --project "$intake_project" --progress=json >"$tmp/intake-progress.json" 2>"$tmp/intake-progress.err"
intake_progress_status=$?
set -e
assert_eq "2" "$intake_progress_status" "unsupported intake progress is an argument error"
assert_eq "" "$(cat "$tmp/intake-progress.err")" "intake progress preflight keeps stderr empty"

if python3 -c 'import jsonschema' >/dev/null 2>&1; then
    for document in "$intake_planned" "$intake_success" "$tmp/intake-blocked.json" "$tmp/intake-progress.json"; do
        assert_success "intake.validate response matches schema" python3 "$ROOT/tools/validate-json.py" --strict \
            --schema "$ROOT/api/schemas/v1.0/operations/intake-validate.schema.json" --document "$document"
    done
fi

# revision.approve must preserve manifest-only mutation and structured outcomes.
(cd "$studio" && "$ROOT/bin/new-mix" "Approval API Project" --client api-client --artist "API Artist" --no-cd >/dev/null)
approval_project="$studio/Clients/API Client/Projects/Approval API Project"
approval_manifest="$approval_project/00_Admin/project-manifest.json"
approval_before="$(cksum "$approval_manifest")"
approval_planned="$tmp/approval-planned.json"
"$ROOT/bin/jl-mixing" revision approve --json --project "$approval_project" --approved-by Client --date 2030-01-01T12:00:00Z --dry-run >"$approval_planned"
assert_eq "$approval_before" "$(cksum "$approval_manifest")" "revision.approve dry-run does not update manifest"
python3 - "$approval_planned" "$approval_project" "$approval_manifest" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["operation"] == "revision.approve"
assert d["status"] == "planned"
assert d["data"]["project"]["path"] == sys.argv[2]
assert d["data"]["revision"]["number"] == 1
assert d["data"]["approved_by"] == "Client"
assert d["data"]["would_update"] == [sys.argv[3]]
PY
pass "revision.approve dry-run is structured and non-mutating"

approval_success="$tmp/approval-success.json"
"$ROOT/bin/jl-mixing" revision approve --json --project "$approval_project" --approved-by Client --date 2030-01-01T12:00:00Z >"$approval_success"
assert_json_eq "1" "$approval_manifest" '.state.approved_revision' "revision.approve updates approved revision"
assert_json_eq "Client" "$approval_manifest" '.revisions[] | select(.number == 1) | .approval.approved_by' "revision.approve records approver"
assert_json_eq "2030-01-01T12:00:00Z" "$approval_manifest" '.revisions[] | select(.number == 1) | .approval.approved_at' "revision.approve records approval date"
python3 - "$approval_success" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["status"] == "success"
assert d["errors"] == []
assert d["data"]["revision"]["number"] == 1
assert d["data"]["approved_by"] == "Client"
assert d["data"]["approved_at"] == "2030-01-01T12:00:00Z"
PY
pass "revision.approve commits structured approval state"

set +e
"$ROOT/bin/jl-mixing" revision approve --json --project "$approval_project" --revision 1 >"$tmp/approval-blocked.json" 2>"$tmp/approval-blocked.err"
approval_status=$?
set -e
assert_eq "5" "$approval_status" "already-approved revision preserves validation exit code"
assert_eq "" "$(cat "$tmp/approval-blocked.err")" "blocked approval keeps stderr empty"
python3 - "$tmp/approval-blocked.json" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["status"] == "blocked"
assert d["errors"][0]["code"] == "REVISION_ALREADY_APPROVED"
PY
pass "revision.approve exposes already-approved state"

set +e
"$ROOT/bin/jl-mixing" revision approve --project "$approval_project" >"$tmp/approval-invalid.json" 2>"$tmp/approval-invalid.err"
approval_invalid_status=$?
set -e
assert_eq "2" "$approval_invalid_status" "revision.approve requires JSON mode"
assert_eq "" "$(cat "$tmp/approval-invalid.err")" "approval preflight keeps stderr empty"

if python3 -c 'import jsonschema' >/dev/null 2>&1; then
    for document in "$approval_planned" "$approval_success" "$tmp/approval-blocked.json" "$tmp/approval-invalid.json"; do
        assert_success "revision.approve response matches schema" python3 "$ROOT/tools/validate-json.py" --strict \
            --schema "$ROOT/api/schemas/v1.0/operations/revision-approve.schema.json" --document "$document"
    done
fi

echo "[OK] Automation API project/revision/intake/approval workflows ($TEST_COUNT assertions)"
