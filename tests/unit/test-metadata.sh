#!/usr/bin/env bash
set -eu

# Purpose: Verify canonical v1.1-schema metadata creation, release provenance, touch, and validation.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
require_test_command jq
. "$ROOT/lib/metadata.sh"

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT
expected_version="$(sed -n '1p' "$ROOT/VERSION")"
assert_eq "jl-mixing $expected_version" "$(jl_created_with)" "created_with version"

cp "$ROOT/examples/client.json" "$tmp/client.json"
jl_metadata_touch "$tmp/client.json" 2026-07-14T12:00:00Z
assert_eq "2026-07-14T12:00:00Z" "$(jl_json_get "$tmp/client.json" '.metadata.last_modified_at')" "metadata touch"
assert_success "mutable example metadata validates" \
    jl_metadata_validate_v11 "$tmp/client.json" mixing-client mutable

printf '1.2.0\n' > "$tmp/VERSION-v12"
v11_mutable="$(JL_MIXING_VERSION_FILE="$tmp/VERSION-v12" \
    jl_metadata_create_v11_mutable mixing-project 1.1.0 \
    44444444-4444-4444-8444-444444444444 2026-07-14T12:00:00Z)"
assert_eq "false" "$(printf '%s' "$v11_mutable" | jq 'has("created_by")')" "v1.1 mutable metadata omits created_by"
assert_eq "2026-07-14T12:00:00Z" "$(printf '%s' "$v11_mutable" | jq -r '.last_modified_at')" "v1.1 mutable metadata starts with matching modification time"
assert_eq "1.1.0" "$(printf '%s' "$v11_mutable" | jq -r '.schema_version')" \
    "v1.2 release retains v1.1 schema version"
assert_eq "jl-mixing 1.2.0" "$(printf '%s' "$v11_mutable" | jq -r '.created_with')" \
    "v1.2 release is recorded independently in created_with"
printf '{"metadata":%s}\n' "$v11_mutable" > "$tmp/v11-mutable.json"
assert_success "v1.1 mutable metadata validates" \
    jl_metadata_validate_v11 "$tmp/v11-mutable.json" mixing-project mutable

v11_immutable="$(JL_MIXING_VERSION_FILE="$tmp/VERSION-v12" \
    jl_metadata_create_v11_immutable mixing-delivery 1.1.0 \
    66666666-6666-4666-8666-666666666666 2026-07-14T13:00:00Z)"
assert_eq "false" "$(printf '%s' "$v11_immutable" | jq 'has("last_modified_at")')" "v1.1 immutable metadata omits last_modified_at"
printf '{"metadata":%s}\n' "$v11_immutable" > "$tmp/v11-immutable.json"
assert_success "v1.1 immutable metadata validates" \
    jl_metadata_validate_v11 "$tmp/v11-immutable.json" mixing-delivery immutable

printf '1.2\n' > "$tmp/VERSION-invalid"
assert_failure "malformed application VERSION is rejected" \
    env JL_MIXING_VERSION_FILE="$tmp/VERSION-invalid" bash -c \
    '. "$1/lib/metadata.sh"; jl_software_version >/dev/null' bash "$ROOT"

echo "[OK] metadata.sh ($TEST_COUNT assertions)"
