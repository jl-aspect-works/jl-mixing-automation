#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
require_test_command python3

if ! python3 -c 'import jsonschema' >/dev/null 2>&1; then
    if [ "${JL_TEST_STRICT:-0}" = "1" ]; then
        echo "[FAIL] managed Client Files API schema checks require jsonschema." >&2
        exit 1
    fi
    echo "[SKIP] managed Client Files API schema checks require jsonschema."
    exit 0
fi

validate() {
    schema="$1"
    document="$2"
    label="$3"
    assert_success "$label" python3 "$ROOT/tools/validate-json.py" --strict \
        --schema "$ROOT/api/schemas/v1.0/operations/$schema" \
        --document "$ROOT/api/examples/v1.0/$document"
}

validate client-files-import-plan.schema.json planned/client-files-import.json "client.files.import.plan planned example matches schema"
validate client-files-import-plan.schema.json blocked/client-files-import.json "client.files.import.plan blocked example matches schema"
validate client-files-import-execute.schema.json success/client-files-import.json "client.files.import.execute success example matches schema"
validate audio-prep-reset-plan.schema.json planned/audio-prep-reset.json "audio.prep.reset.plan planned example matches schema"
validate audio-prep-reset-execute.schema.json success/audio-prep-reset.json "audio.prep.reset.execute success example matches schema"
validate audio-prep-reset-execute.schema.json error/audio-prep-reset.json "audio.prep.reset.execute error example matches schema"

echo "[OK] Managed Client Files API schemas/examples ($TEST_COUNT assertions)"
