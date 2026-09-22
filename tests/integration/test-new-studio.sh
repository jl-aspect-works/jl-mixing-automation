#!/usr/bin/env bash
set -eu

# Purpose: exercise the complete v1.1 studio creation contract, including
# strict output, schema generation, dry-run safety, removed-option diagnostics,
# and transaction rollback.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/integration/integration-helper.sh"
expected_created_with="jl-mixing $(cat "$ROOT/VERSION")"

require_test_command jq
require_test_command python3
python3 -c 'import jsonschema' >/dev/null 2>&1 || {
    if [ "${JL_TEST_STRICT:-0}" = "1" ]; then
        fail "new-studio integration tests require jsonschema"
    fi
    echo "[SKIP] new-studio integration tests require jsonschema."
    exit 0
}

capture_failure() {
    local output_file
    output_file="$1"
    shift
    set +e
    "$@" >"$output_file" 2>&1
    CAPTURE_STATUS=$?
    set -e
}

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
studio_root="$tmp/North Shore Studio"

output="$(JL_MIXING_SHELL_INTEGRATION=1 "$ROOT/bin/new-studio" \
    --root "$studio_root" \
    --name 'North Shore Mixing' \
    --engineer ' Jake ' \
    --sample-rate 96000 \
    --bit-depth 32 \
    --file-format aiff \
    --default-cd)"

assert_contains "$output" 'Studio created successfully.' "success heading"
assert_contains "$output" 'Shell integration:           active' "active shell integration reported"
assert_contains "$output" 'Next:' "next heading retained"
assert_contains "$output" 'new-client <client-id>' "next command retained"
assert_dir_exists "$studio_root/Clients"
assert_dir_exists "$studio_root/Studio"
assert_file_exists "$studio_root/Studio/studio.json"
assert_path_not_exists "$studio_root/DAWs"

studio_json="$studio_root/Studio/studio.json"
assert_json_eq "mixing-studio" "$studio_json" '.metadata.schema' "studio schema name"
assert_json_eq "1.1.0" "$studio_json" '.metadata.schema_version' "studio schema version"
assert_json_eq "$expected_created_with" "$studio_json" '.metadata.created_with' \
    "created_with version"
assert_json_eq "north-shore-mixing" "$studio_json" '.studio_id' "derived studio ID"
assert_json_eq "North Shore Mixing" "$studio_json" '.studio_name' "trimmed studio name"
assert_json_eq "$studio_root" "$studio_json" '.root_path' "absolute root path"
assert_json_eq "Jake" "$studio_json" '.defaults.mix_engineer' "trimmed engineer default"
assert_json_eq "96000" "$studio_json" '.defaults.audio.sample_rate' "sample-rate default"
assert_json_eq "32" "$studio_json" '.defaults.audio.bit_depth' "bit-depth default"
assert_json_eq "AIFF" "$studio_json" '.defaults.audio.file_format' "normalized file format"
assert_json_eq "Cloud transfer" "$studio_json" '.defaults.delivery.method' "delivery method default"
assert_eq '["main_mix","instrumental"]' \
    "$(jq -c '.defaults.delivery.requested_deliverables' "$studio_json")" \
    "requested deliverables default"
assert_eq "true" "$(jq -r '.cli.change_directory_after_create' "$studio_json")" \
    "automatic directory preference"
assert_eq "false" "$(jq -r '.metadata | has("created_by")' "$studio_json")" \
    "created_by removed"
assert_eq "false" "$(jq -r 'has("default_daw")' "$studio_json")" \
    "DAW default removed"
assert_success "generated studio validates against canonical schema" \
    "$ROOT/tools/validate-json.py" --strict \
    --schema "$ROOT/schemas/studio.schema.json" --document "$studio_json"

# Existing destinations are protected, including a valid workspace.
capture_failure "$tmp/existing.out" "$ROOT/bin/new-studio" --root "$studio_root"
assert_eq "6" "$CAPTURE_STATUS" "existing studio uses unsafe-operation exit"
assert_contains "$(cat "$tmp/existing.out")" 'Studio root already exists' \
    "existing studio diagnostic"

# A dangling symlink is still an occupied destination and must not be adopted.
ln -s "$tmp/does-not-exist" "$tmp/dangling-studio"
capture_failure "$tmp/symlink.out" "$ROOT/bin/new-studio" --root "$tmp/dangling-studio"
assert_eq "6" "$CAPTURE_STATUS" "symlink destination uses unsafe-operation exit"
assert_contains "$(cat "$tmp/symlink.out")" 'Studio root already exists' \
    "symlink collision diagnostic"

# Dry-run performs validation but leaves no filesystem entry behind.
dry_root="$tmp/Dry Run Studio"
dry_output="$("$ROOT/bin/new-studio" --root "$dry_root" --no-default-cd --dry-run)"
assert_contains "$dry_output" 'Dry run — no changes made.' "dry-run heading"
assert_contains "$dry_output" 'Would create:' "dry-run structure"
assert_contains "$dry_output" 'After creation:' "dry-run next-step label"
assert_contains "$dry_output" 'new-client <client-id>' "dry-run next command"
assert_path_not_exists "$dry_root"

# Explicit --root overrides JL_MIXING_ROOT.
env_output="$(JL_MIXING_ROOT="$tmp/Environment Root" "$ROOT/bin/new-studio" \
    --root "$tmp/Explicit Root" --dry-run)"
assert_contains "$env_output" "$tmp/Explicit Root" "explicit root precedence"

# Removed v1.0 options fail with targeted migration diagnostics.
capture_failure "$tmp/daw.out" "$ROOT/bin/new-studio" --daw 'Logic Pro'
assert_eq "2" "$CAPTURE_STATUS" "removed --daw exit status"
assert_contains "$(cat "$tmp/daw.out")" '--daw was removed in JL Mixing 1.1' \
    "removed --daw diagnostic"

capture_failure "$tmp/noninteractive.out" "$ROOT/bin/new-studio" --non-interactive
assert_eq "2" "$CAPTURE_STATUS" "removed --non-interactive exit status"
assert_contains "$(cat "$tmp/noninteractive.out")" '--non-interactive was removed in JL Mixing 1.1' \
    "removed --non-interactive diagnostic"

capture_failure "$tmp/cd-conflict.out" "$ROOT/bin/new-studio" \
    --root "$tmp/CD Conflict" --default-cd --no-default-cd
assert_eq "2" "$CAPTURE_STATUS" "conflicting directory defaults rejected"
assert_contains "$(cat "$tmp/cd-conflict.out")" 'cannot be used together' \
    "directory-default conflict diagnostic"

capture_failure "$tmp/missing-parent.out" "$ROOT/bin/new-studio" \
    --root "$tmp/missing/Studio"
assert_eq "4" "$CAPTURE_STATUS" "missing parent uses context exit"
assert_contains "$(cat "$tmp/missing-parent.out")" 'parent must be an existing directory' \
    "missing parent diagnostic"

# A failure after the atomic rename removes only the root created by this run.
rollback_root="$tmp/Rollback Studio"
capture_failure "$tmp/rollback.out" env JL_MIXING_FAIL_AT=after-directory-commit \
    "$ROOT/bin/new-studio" --root "$rollback_root"
[ "$CAPTURE_STATUS" -ne 0 ] || fail "injected transaction failure was not reported"
pass "injected transaction failure is reported"
assert_path_not_exists "$rollback_root"
assert_eq "" "$(find "$tmp" -maxdepth 1 -name '.Rollback Studio.stage.*' -print)" \
    "staging directory cleaned after failure"

printf '[OK] new-studio (%s assertions)\n' "$TEST_COUNT"
