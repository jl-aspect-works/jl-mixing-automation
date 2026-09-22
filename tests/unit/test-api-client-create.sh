#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
require_test_command python3

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
studio="$tmp/Studio Root"
"$ROOT/bin/new-studio" --root "$studio" --name "API Test Studio" --engineer "Jake" --no-default-cd >/dev/null

planned="$tmp/planned.json"
(cd "$studio" && "$ROOT/bin/jl-mixing" client create api-client --json --name "API Client" --dry-run >"$planned")
assert_path_not_exists "$studio/Clients/API Client"
python3 - "$planned" "$studio" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["api_version"] == "1.0"
assert d["operation"] == "client.create"
assert d["status"] == "planned"
assert d["errors"] == [] and d["warnings"] == []
assert d["data"]["client"]["id"] == "api-client"
assert Path(d["data"]["workspace_path"]) == Path(sys.argv[2])
PY
pass "client.create dry-run is structured and non-mutating"

success="$tmp/success.json"
(cd "$studio" && "$ROOT/bin/jl-mixing" client create api-client --json --name "API Client" --artist "Artist Name" >"$success")
assert_file_exists "$studio/Clients/API Client/client.json"
python3 - "$success" "$studio/Clients/API Client/client.json" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
c=json.loads(Path(sys.argv[2]).read_text())
assert d["status"] == "success"
assert d["data"]["client"]["id"] == c["client_id"] == "api-client"
assert c["defaults"]["artist"] == "Artist Name"
assert Path(d["data"]["configuration_path"]) == Path(sys.argv[2])
PY
pass "client.create commits authoritative client state"

set +e
(cd "$studio" && "$ROOT/bin/jl-mixing" client create api-client --json --name "Other" >"$tmp/duplicate.json" 2>"$tmp/duplicate.err")
status=$?
set -e
assert_eq "5" "$status" "duplicate client preserves validation exit code"
assert_eq "" "$(cat "$tmp/duplicate.err")" "API failures keep stderr empty"
python3 - "$tmp/duplicate.json" <<'PY'
import json, sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["status"] == "blocked"
assert d["errors"][0]["code"] == "CLIENT_ALREADY_EXISTS"
PY
pass "duplicate client returns stable machine error"



if python3 -c 'import jsonschema' >/dev/null 2>&1; then
    for document in "$planned" "$success" "$tmp/duplicate.json"; do
        assert_success "client.create response matches schema" python3 "$ROOT/tools/validate-json.py" --strict \
            --schema "$ROOT/api/schemas/v1.0/operations/client-create.schema.json" --document "$document"
    done
else
    echo "[SKIP] client.create schema validation requires jsonschema."
fi

echo "[OK] Automation API client.create ($TEST_COUNT assertions)"
