#!/usr/bin/env bash
set -eu

# Purpose: Verify v1.1 naming and cross-workspace availability rules.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
require_test_command jq
. "$ROOT/lib/validation.sh"

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT

assert_success "valid slug" jl_validate_slug acme-records
assert_failure "invalid slug" jl_validate_slug 'Acme Records'
assert_success "valid project name" jl_validate_project_name 'Blue Sky'
assert_failure "slash rejected in project name" jl_validate_project_name 'Blue/Sky'
assert_success "valid sample rate" jl_validate_sample_rate 48000
assert_failure "invalid sample rate" jl_validate_sample_rate 12345
assert_success "valid bit depth" jl_validate_bit_depth 24
assert_failure "invalid bit depth" jl_validate_bit_depth 20
assert_success "valid file format" jl_validate_file_format WAV
assert_failure "invalid file format" jl_validate_file_format FLAC

assert_success "canonical folder name accepted" jl_validate_folder_name 'Blue Sky'
assert_failure "unsanitized folder name rejected" jl_validate_folder_name 'Blue/Sky'

mkdir -p "$tmp/studio/Clients/Acme" "$tmp/studio/Clients/Other"
cat > "$tmp/studio/Clients/Acme/client.json" <<'EOF_CLIENT'
{"metadata":{"document_id":"11111111-1111-4111-8111-111111111111"},"client_id":"acme"}
EOF_CLIENT
assert_failure "case-insensitive existing client ID rejected" \
    jl_validate_client_id_available "$tmp/studio" ACME
assert_success "new client ID accepted" jl_validate_client_id_available "$tmp/studio" other

mkdir -p "$tmp/studio/Clients/Acme/Projects/Blue Sky/00_Admin"
cat > "$tmp/studio/Clients/Acme/Projects/Blue Sky/00_Admin/project-manifest.json" <<'EOF_PROJECT'
{"metadata":{"document_id":"22222222-2222-4222-8222-222222222222"},"project_id":"blue-sky"}
EOF_PROJECT
assert_failure "case-insensitive existing project ID rejected" \
    jl_validate_project_id_available "$tmp/studio/Clients/Acme" BLUE-SKY
assert_success "new project ID accepted" \
    jl_validate_project_id_available "$tmp/studio/Clients/Acme" second-project

echo "[OK] validation.sh ($TEST_COUNT assertions)"
