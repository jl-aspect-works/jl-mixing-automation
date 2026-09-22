#!/usr/bin/env bash
set -eu

# Purpose: Verify JSON reads, atomic mutations, exact schema identities, independent creator provenance, and UUID uniqueness.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
require_test_command jq
. "$ROOT/lib/json.sh"

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT
cp "$ROOT/examples/client.json" "$tmp/client.json"

assert_success "valid JSON detected" jl_json_is_valid "$tmp/client.json"
assert_eq "acme" "$(jl_json_get "$tmp/client.json" '.client_id')" "read JSON string"
jl_json_set_string "$tmp/client.json" '.client_name' 'Acme Updated'
assert_eq "Acme Updated" "$(jl_json_get "$tmp/client.json" '.client_name')" "atomic string update"
jl_json_set_value "$tmp/client.json" '.defaults.audio.sample_rate' '96000'
assert_eq "96000" "$(jl_json_get "$tmp/client.json" '.defaults.audio.sample_rate')" "atomic JSON value update"
assert_success "schema identity accepted" jl_json_require_schema_identity "$tmp/client.json" mixing-client 1
assert_failure "wrong schema rejected" jl_json_require_schema_identity "$tmp/client.json" mixing-project 1
assert_eq "1" "$(jl_json_schema_major "$tmp/client.json")" "schema major extracted"
assert_success "exact schema identity accepted" \
    jl_json_require_exact_schema_identity "$tmp/client.json" mixing-client 1.1.0
jq '.metadata.schema_version="1.0.4"' "$tmp/client.json" > "$tmp/client-v10.json"
assert_failure "v1.0 exact schema rejected" \
    jl_json_require_exact_schema_identity "$tmp/client-v10.json" mixing-client 1.1.0
assert_failure "different exact v1.1 version rejected" \
    jl_json_require_exact_schema_identity "$tmp/client.json" mixing-client 1.1.1
assert_success "v1.1 created_with release accepted" \
    jl_json_require_created_with_semver "$tmp/client.json"
jq '.metadata.created_with="jl-mixing 1.2.0"' "$tmp/client.json" > "$tmp/client-v12.json"
assert_success "creator release is independent of schema version" \
    jl_json_require_created_with_semver "$tmp/client-v12.json"
assert_success "legacy created_with validator alias remains compatible" \
    jl_json_require_created_with_series "$tmp/client-v12.json" 1.1.0
jq '.metadata.created_with="jl-mixing 1.2"' "$tmp/client.json" > "$tmp/client-bad-semver.json"
assert_failure "malformed created_with semantic version rejected" \
    jl_json_require_created_with_semver "$tmp/client-bad-semver.json"
jq '.metadata.created_with="other-app 1.2.0"' "$tmp/client.json" > "$tmp/client-wrong-product.json"
assert_failure "non-JL-Mixing creator rejected" \
    jl_json_require_created_with_semver "$tmp/client-wrong-product.json"
assert_eq "$ROOT/schemas/client.schema.json" \
    "$(jl_json_schema_path client.schema.json)" "local schema path resolved"
assert_failure "schema path traversal rejected" jl_json_schema_path '../client.schema.json'

mkdir -p "$tmp/studio/Studio" "$tmp/studio/Clients/Acme"
cp "$tmp/client.json" "$tmp/studio/Clients/Acme/client.json"
cp "$ROOT/examples/studio.json" "$tmp/studio/Studio/studio.json"
assert_success "unique studio document IDs accepted" jl_json_validate_unique_document_ids "$tmp/studio"
assert_failure "existing document ID rejected" \
    jl_json_assert_document_id_available "$tmp/studio" 22222222-2222-4222-8222-222222222222
assert_success "new document ID accepted" \
    jl_json_assert_document_id_available "$tmp/studio" 99999999-9999-4999-8999-999999999999
mkdir -p "$tmp/studio/Clients/Acme/Projects/Blue Sky/00_Admin"
jq -n '{metadata:{document_id:"44444444-4444-4444-8444-444444444444"},revisions:[{revision_id:"55555555-5555-4555-8555-555555555555"}]}' \
    > "$tmp/studio/Clients/Acme/Projects/Blue Sky/00_Admin/project-manifest.json"
assert_failure "existing revision UUID rejected" \
    jl_json_assert_uuid_available "$tmp/studio" 55555555-5555-4555-8555-555555555555
mkdir -p "$tmp/studio/Clients/Other"
cp "$tmp/studio/Clients/Acme/client.json" "$tmp/studio/Clients/Other/client.json"
assert_failure "duplicate studio document IDs rejected" jl_json_validate_unique_document_ids "$tmp/studio"
echo "[OK] json.sh ($TEST_COUNT assertions)"
