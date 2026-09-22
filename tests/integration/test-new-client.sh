#!/usr/bin/env bash
set -eu

# Purpose: Exercise the complete v1.1 client-creation contract.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/integration/integration-helper.sh"
expected_created_with="jl-mixing $(cat "$ROOT/VERSION")"

require_test_command jq
require_test_command python3
python3 -c 'import jsonschema' >/dev/null 2>&1 || {
    if [ "${JL_TEST_STRICT:-0}" = "1" ]; then
        fail "jsonschema is required for strict new-client tests"
    fi
    echo "[SKIP] new-client integration tests require jsonschema."
    exit 0
}

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT

create_studio() {
    local root
    root="$1"
    shift
    "$ROOT/bin/new-studio" --root "$root" --name "JL Mix Studio" --engineer "Jake" "$@" >/dev/null
}

run_client() {
    local root
    root="$1"
    shift
    JL_MIXING_ROOT="$root" "$ROOT/bin/new-client" "$@"
}

studio_root="$tmp/studio"
create_studio "$studio_root"

# Explicit values override studio defaults and produce the minimal flattened
# client structure.
output="$(run_client "$studio_root" acme \
    --name "Acme Records" \
    --artist "The Acmes" \
    --sample-rate 96000 \
    --bit-depth 32 \
    --file-format aiff \
    --delivery-method "Secure portal" \
    --deliverables 'stems, main_mix')"
client_root="$studio_root/Clients/Acme Records"
client_file="$client_root/client.json"
assert_dir_exists "$client_root"
assert_dir_exists "$client_root/Projects"
assert_path_not_exists "$client_root/Projects/Active"
assert_path_not_exists "$client_root/Projects/Completed"
assert_file_exists "$client_file"
assert_json_eq "mixing-client" "$client_file" '.metadata.schema' "client schema identity"
assert_json_eq "1.1.0" "$client_file" '.metadata.schema_version' "client schema version"
assert_json_eq "$expected_created_with" "$client_file" '.metadata.created_with' \
    "client creator release"
assert_json_eq "acme" "$client_file" '.client_id' "client ID"
assert_json_eq "Acme Records" "$client_file" '.client_name' "client display name"
assert_json_eq "The Acmes" "$client_file" '.defaults.artist' "artist default"
assert_json_eq "96000" "$client_file" '.defaults.audio.sample_rate' "sample-rate override"
assert_json_eq "32" "$client_file" '.defaults.audio.bit_depth' "bit-depth override"
assert_json_eq "AIFF" "$client_file" '.defaults.audio.file_format' "file-format normalization"
assert_json_eq "Secure portal" "$client_file" '.defaults.delivery.method' "delivery-method override"
assert_eq '["stems","main_mix"]' "$(jq -c '.defaults.delivery.requested_deliverables' "$client_file")" \
    "deliverable order preserved"
assert_eq "false" "$(jq -r '.metadata | has("created_by")' "$client_file")" \
    "removed created_by is absent"
assert_contains "$output" 'Client created successfully.' "success heading"
assert_contains "$output" 'new-mix --project "PROJECT NAME"' "next command retained"
assert_contains "$output" "cd '$client_root'" "copy-and-paste cd retained"
python3 "$ROOT/tools/validate-json.py" --strict \
    --schema "$ROOT/schemas/client.schema.json" --document "$client_file" >/dev/null
pass "generated client validates against canonical schema"

# Omitted values inherit the studio snapshot and the display name derives from
# the immutable slug.
run_client "$studio_root" beta-audio >/dev/null
beta_file="$studio_root/Clients/Beta Audio/client.json"
assert_file_exists "$beta_file"
assert_json_eq "Beta Audio" "$beta_file" '.client_name' "default display name"
assert_json_eq "48000" "$beta_file" '.defaults.audio.sample_rate' "inherited sample rate"
assert_json_eq "24" "$beta_file" '.defaults.audio.bit_depth' "inherited bit depth"
assert_json_eq "WAV" "$beta_file" '.defaults.audio.file_format' "inherited file format"
assert_json_eq "Cloud transfer" "$beta_file" '.defaults.delivery.method' "inherited delivery method"
assert_eq '["main_mix","instrumental"]' \
    "$(jq -c '.defaults.delivery.requested_deliverables' "$beta_file")" \
    "inherited deliverables"

# Readable folder sanitization is deterministic and does not change the stored
# display name.
run_client "$studio_root" smith-jones --name 'Smith / Jones Productions' >/dev/null
sanitized_root="$studio_root/Clients/Smith - Jones Productions"
assert_dir_exists "$sanitized_root"
assert_json_eq 'Smith / Jones Productions' "$sanitized_root/client.json" '.client_name' \
    "unsanitized display name preserved"

# Duplicate IDs and case-insensitive folder collisions are rejected without
# creating suffixes or partial clients.
assert_failure "duplicate client ID is protected" \
    run_client "$studio_root" acme --name "Another Name"
assert_failure "case-insensitive folder collision is protected" \
    run_client "$studio_root" another-acme --name "ACME RECORDS"
assert_path_not_exists "$studio_root/Clients/Another Name"

# Dry-run resolves inherited values and reports the complete plan without
# generating a client directory.
dry_output="$(run_client "$studio_root" dry-client --name 'Dry Client' --dry-run)"
assert_contains "$dry_output" 'Dry run — no changes made.' "dry-run heading"
assert_contains "$dry_output" 'client.json' "dry-run file plan"
assert_contains "$dry_output" 'Projects/' "dry-run directory plan"
assert_contains "$dry_output" 'new-mix --project "PROJECT NAME"' "dry-run next command"
assert_path_not_exists "$studio_root/Clients/Dry Client"

# Invalid identities, names, defaults, and deliverable lists fail before any
# filesystem mutation.
assert_failure "uppercase client ID rejected" run_client "$studio_root" Bad-ID
assert_failure "consecutive client-ID hyphens rejected" run_client "$studio_root" bad--id
assert_failure "empty explicit name rejected" run_client "$studio_root" empty-name --name ""
assert_failure "reserved folder name rejected" run_client "$studio_root" reserved --name CON
assert_failure "unsupported sample rate rejected" run_client "$studio_root" bad-rate --sample-rate 22050
assert_failure "empty delivery method rejected" run_client "$studio_root" no-method --delivery-method ""
assert_failure "empty deliverables rejected" run_client "$studio_root" no-deliverables --deliverables ""
assert_failure "empty deliverable entry rejected" run_client "$studio_root" empty-entry --deliverables 'main_mix,,stems'
assert_failure "duplicate deliverables rejected" run_client "$studio_root" duplicate-types --deliverables 'stems,stems'
assert_failure "unsupported deliverable rejected" run_client "$studio_root" bad-type --deliverables 'main_mix,other'

# Removed v1.0 options return targeted migration guidance.
set +e
removed_output="$(run_client "$studio_root" removed-limit --revision-limit 2 2>&1)"
removed_status=$?
set -e
[ "$removed_status" -ne 0 ] || fail "removed --revision-limit unexpectedly succeeded"
assert_contains "$removed_output" '--revision-limit was removed in JL Mixing 1.1.' \
    "revision-limit diagnostic"
set +e
removed_output="$(run_client "$studio_root" removed-interactive --non-interactive 2>&1)"
removed_status=$?
set -e
[ "$removed_status" -ne 0 ] || fail "removed --non-interactive unexpectedly succeeded"
assert_contains "$removed_output" '--non-interactive was removed in JL Mixing 1.1.' \
    "non-interactive diagnostic"

# Per-command directory flags validate their combinations. A secure private
# result file receives the committed absolute path only after success.
assert_failure "--cd and --no-cd are mutually exclusive" \
    run_client "$studio_root" conflicting-cd --cd --no-cd
assert_failure "--cd is incompatible with dry-run" \
    run_client "$studio_root" dry-cd --cd --dry-run
cd_result="$tmp/cd-result"
: > "$cd_result"
chmod 600 "$cd_result"
cd_output="$(JL_MIXING_CD_RESULT_FILE="$cd_result" run_client "$studio_root" cd-client --cd)"
cd_client_root="$studio_root/Clients/Cd Client"
assert_eq "$cd_client_root" "$(cat "$cd_result")" "explicit cd result path"
assert_contains "$cd_output" 'new-mix --project "PROJECT NAME"' "cd-mode next command"
case "$cd_output" in
    *"cd '$cd_client_root'"*) fail "successful result channel printed redundant cd command" ;;
    *) pass "successful result channel omits redundant cd command" ;;
esac

fallback_output="$(run_client "$studio_root" fallback-client --cd)"
fallback_root="$studio_root/Clients/Fallback Client"
assert_contains "$fallback_output" 'integration is not active.' "missing integration warning"
assert_contains "$fallback_output" "cd '$fallback_root'" "fallback cd command"

# Studio default directory behavior can be overridden explicitly.
cd_studio="$tmp/cd-studio"
create_studio "$cd_studio" --default-cd
: > "$cd_result"
JL_MIXING_CD_RESULT_FILE="$cd_result" run_client "$cd_studio" default-cd >/dev/null
assert_eq "$cd_studio/Clients/Default Cd" "$(cat "$cd_result")" "studio default cd result"
: > "$cd_result"
JL_MIXING_CD_RESULT_FILE="$cd_result" run_client "$cd_studio" stay-put --no-cd >/dev/null
assert_eq "" "$(cat "$cd_result")" "explicit no-cd overrides studio default"

# Transaction failure after the staged-directory rename removes only the new
# client and leaves all pre-existing clients unchanged.
assert_failure "injected commit failure rolls back new client" \
    env JL_MIXING_ROOT="$studio_root" JL_MIXING_FAIL_AT=after-directory-commit \
        "$ROOT/bin/new-client" rollback-client
assert_path_not_exists "$studio_root/Clients/Rollback Client"
assert_file_exists "$client_file"

# Existing files, directories, and symlinks at a case-insensitive destination
# are never adopted or overwritten.
touch "$studio_root/Clients/Occupied"
assert_failure "existing file destination rejected" \
    run_client "$studio_root" occupied-file --name Occupied
rm -f "$studio_root/Clients/Occupied"
ln -s "$tmp" "$studio_root/Clients/Linked Client"
assert_failure "symlink destination rejected" \
    run_client "$studio_root" linked-client --name 'Linked Client'
[ -L "$studio_root/Clients/Linked Client" ] || fail "existing symlink was modified"
pass "existing symlink preserved"

# Recognizable v1.0 workspaces are rejected without modification.
legacy_root="$tmp/legacy-studio"
fixture_studio "$legacy_root"
assert_failure "legacy workspace rejected" run_client "$legacy_root" legacy-client
assert_path_not_exists "$legacy_root/Clients/Legacy Client"

printf '[OK] new-client (%s assertions)\n' "$TEST_COUNT"
