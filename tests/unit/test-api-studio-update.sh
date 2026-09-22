#!/usr/bin/env bash
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
require_test_command python3

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
studio="$tmp/Studio Root"
mkdir -p "$studio/Studio" "$studio/Clients"

python3 - "$studio" <<'PY_FIXTURE'
import json
from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve()
doc = {
    "metadata": {
        "schema": "mixing-studio", "schema_version": "1.1.0",
        "document_id": "44444444-4444-4444-4444-444444444444",
        "created_with": "jl-mixing 2.0.0",
        "created_at": "2030-01-01T12:00:00Z", "last_modified_at": "2030-01-01T12:00:00Z"
    },
    "studio_id": "api-studio", "studio_name": "API Studio", "root_path": str(root),
    "defaults": {
        "mix_engineer": "Engineer",
        "audio": {"sample_rate": 48000, "bit_depth": 24, "file_format": "WAV"},
        "delivery": {"method": "Cloud transfer", "requested_deliverables": ["main_mix", "instrumental"]}
    },
    "cli": {"change_directory_after_create": False}
}
(root / "Studio" / "studio.json").write_text(json.dumps(doc) + "\n", encoding="utf-8")
PY_FIXTURE

config="$studio/Studio/studio.json"
cp "$config" "$tmp/original.json"

(
    cd "$studio"
    "$ROOT/bin/jl-mixing" studio update --json --name "Planned Studio" --dry-run >"$tmp/planned.json" 2>"$tmp/planned.err"
)
assert_eq "" "$(cat "$tmp/planned.err")" "studio.update dry-run keeps stderr empty"
assert_eq "$(cat "$tmp/original.json")" "$(cat "$config")" "studio.update dry-run is non-mutating"
assert_success "studio.update planned response matches schema" \
    python3 "$ROOT/tools/validate-json.py" --strict \
        --schema "$ROOT/api/schemas/v1.0/operations/studio-update.schema.json" \
        --document "$tmp/planned.json"

(
    cd "$studio"
    "$ROOT/bin/jl-mixing" studio update --json \
        --name "Renamed Studio" --engineer "New Engineer" \
        --sample-rate 96000 --bit-depth 32 --file-format aiff \
        --delivery-method "Secure upload" --deliverables main_mix,stems \
        >"$tmp/success.json" 2>"$tmp/success.err"
)
assert_eq "" "$(cat "$tmp/success.err")" "studio.update success keeps stderr empty"
python3 - "$config" <<'PY_ASSERT'
import json, sys
from pathlib import Path
doc = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert doc["studio_id"] == "api-studio"
assert doc["studio_name"] == "Renamed Studio"
assert doc["defaults"]["audio"] == {"sample_rate": 96000, "bit_depth": 32, "file_format": "AIFF"}
assert doc["defaults"]["delivery"]["requested_deliverables"] == ["main_mix", "stems"]
assert doc["cli"] == {"change_directory_after_create": False}
assert doc["metadata"]["document_id"] == "44444444-4444-4444-4444-444444444444"
PY_ASSERT
pass "studio.update commits editable values without changing identity"
assert_success "studio.update success response matches schema" \
    python3 "$ROOT/tools/validate-json.py" --strict \
        --schema "$ROOT/api/schemas/v1.0/operations/studio-update.schema.json" \
        --document "$tmp/success.json"

cp "$config" "$tmp/before-invalid.json"
set +e
(
    cd "$studio"
    "$ROOT/bin/jl-mixing" studio update --json --sample-rate 12345 >"$tmp/blocked.json" 2>"$tmp/blocked.err"
)
status=$?
set -e
assert_eq "5" "$status" "studio.update invalid value preserves validation exit code"
assert_eq "" "$(cat "$tmp/blocked.err")" "studio.update blocked response keeps stderr empty"
assert_eq "$(cat "$tmp/before-invalid.json")" "$(cat "$config")" "studio.update blocked update preserves original document"
assert_success "studio.update blocked response matches schema" \
    python3 "$ROOT/tools/validate-json.py" --strict \
        --schema "$ROOT/api/schemas/v1.0/operations/studio-update.schema.json" \
        --document "$tmp/blocked.json"

cp "$config" "$tmp/before-failure.json"
set +e
(
    cd "$studio"
    JL_MIXING_FAIL_AT=after-file-replacement "$ROOT/bin/jl-mixing" studio update --json --name "Rollback" >"$tmp/error.json" 2>"$tmp/error.err"
)
status=$?
set -e
assert_failure "studio.update injected transaction failure returns non-zero" test "$status" -eq 0
assert_eq "$(cat "$tmp/before-failure.json")" "$(cat "$config")" "studio.update transaction failure rolls back original document"
assert_success "studio.update error response matches schema" \
    python3 "$ROOT/tools/validate-json.py" --strict \
        --schema "$ROOT/api/schemas/v1.0/operations/studio-update.schema.json" \
        --document "$tmp/error.json"

echo "[OK] Automation API studio.update ($TEST_COUNT assertions)"
