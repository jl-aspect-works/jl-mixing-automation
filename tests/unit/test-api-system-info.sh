#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
require_test_command python3

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
stdout_file="$tmp/system-info.json"
stderr_file="$tmp/system-info.stderr"
"$ROOT/bin/jl-mixing" system-info --json >"$stdout_file" 2>"$stderr_file"
assert_eq "" "$(cat "$stderr_file")" "system-info keeps stderr empty"
python3 - "$stdout_file" "$ROOT" <<'PY_ASSERT'
import json
from pathlib import Path
import sys
p=Path(sys.argv[1]); root=Path(sys.argv[2]).resolve(); d=json.loads(p.read_text())
av=(root/'API_VERSION').read_text().strip(); app=(root/'VERSION').read_text().strip()
assert d['api_version']==av
assert d['application']=={'name':'jl-mixing','version':app}
assert d['metadata']=={'readable_schema_versions':['1.1.0'],'writable_schema_version':'1.1.0'}
assert d['capabilities']==[
'audio.prep.provenance.sha256','audio.prep.reset.execute','audio.prep.reset.plan','audio.prep.validation.structured',
'client.create','client.create.explicit-context','client.update','client.files.import.execute','client.files.import.plan',
'delivery.create','delivery.package.delete','delivery.package.rebuild','delivery.status','intake.validate',
'intake.validate.incremental','intake.validate.report','intake.validate.structured','project.create','project.create.artist',
'project.update','revision.approve','revision.close','revision.create','revision.create.description','revision.reopen',
'revision.unapprove','revision.update.description','studio.update','system.info']
assert Path(d['schemas']['installed_path']).resolve()==(root/'api'/'schemas'/f'v{av}').resolve()
assert d['schemas']['public_base_url']==f'https://jlaudio.github.io/jl-mixing/api/v{av}/schemas/'
PY_ASSERT
pass "system-info reports independent API, application, and metadata versions"

if python3 -c 'import jsonschema' >/dev/null 2>&1; then
    assert_success "system-info JSON matches its published schema" python3 "$ROOT/tools/validate-json.py" --strict --schema "$ROOT/api/schemas/v1.0/system-info.schema.json" --document "$stdout_file"
    compatible_file="$tmp/system-info-compatible.json"
    python3 - "$stdout_file" "$compatible_file" <<'PY_COMPATIBLE'
import json
from pathlib import Path
import sys
source,destination=map(Path,sys.argv[1:]); d=json.loads(source.read_text()); d['future_optional_field']={'enabled':True}; d['application']['future_build_metadata']='example'; d['metadata']['future_optional_schema_policy']='additive'; d['schemas']['future_optional_format']='json-schema'; destination.write_text(json.dumps(d)+'\n')
PY_COMPATIBLE
    assert_success "API 1.0 schema accepts additive optional fields" python3 "$ROOT/tools/validate-json.py" --strict --schema "$ROOT/api/schemas/v1.0/system-info.schema.json" --document "$compatible_file"
else
    echo "[SKIP] system-info schema validation requires jsonschema."
fi
assert_failure "system-info requires JSON mode" "$ROOT/bin/jl-mixing" system-info
assert_failure "system-info rejects extra arguments" "$ROOT/bin/jl-mixing" system-info --json extra
assert_failure "unknown API command is rejected" "$ROOT/bin/jl-mixing" unknown --json
printf '1\n' > "$tmp/API_VERSION-invalid"
assert_failure "malformed API version is rejected" env JL_MIXING_API_VERSION_FILE="$tmp/API_VERSION-invalid" "$ROOT/bin/jl-mixing" system-info --json
printf '9.8\n' > "$tmp/API_VERSION-missing-schema"
assert_failure "API version without installed schemas is rejected" env JL_MIXING_API_VERSION_FILE="$tmp/API_VERSION-missing-schema" "$ROOT/bin/jl-mixing" system-info --json
echo "[OK] Automation API system-info ($TEST_COUNT assertions)"
