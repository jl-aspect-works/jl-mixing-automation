#!/usr/bin/env bash
set -eu

# Purpose: Verify exact v1.1 context discovery plus clear legacy-layout rejection.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
require_test_command jq
. "$ROOT/lib/context.sh"

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT

v11="$tmp/v11"
v11_project="$v11/Clients/Acme Records/Projects/Blue Sky"
mkdir -p "$v11/Studio" "$v11/Clients/Acme Records" \
    "$v11_project/00_Admin" "$v11_project/04_Revisions/Revision_01/sub" \
    "$v11_project/05_Final_Delivery"
jq --arg root "$v11" '.root_path=$root' "$ROOT/examples/studio.json" > "$v11/Studio/studio.json"
cp "$ROOT/examples/client.json" "$v11/Clients/Acme Records/client.json"
jq '.state.current_revision=1 | .state.approved_revision=null | .state.delivered_revision=null |
    .revisions=[.revisions[0] | .approval={approved_at:null,approved_by:null}]' \
    "$ROOT/examples/project-manifest.json" > "$v11_project/00_Admin/project-manifest.json"

assert_success "v1.1 workspace accepted" jl_context_require_v11_workspace "$v11"
assert_eq "$v11" "$(jl_context_studio_root_v11 "$v11_project/04_Revisions/Revision_01/sub")" "v1.1 studio marker discovery"
assert_eq "$v11/Clients/Acme Records" "$(jl_context_client_root_v11 "$v11_project/04_Revisions/Revision_01/sub")" "v1.1 client marker discovery"
assert_eq "$v11/Clients/Acme Records" "$(jl_context_resolve_client_v11 "$v11/Clients/Acme Records" /tmp)" "explicit v1.1 client resolution"
assert_eq "$v11_project" "$(jl_context_project_root_v11 "$v11_project/04_Revisions/Revision_01/sub")" "v1.1 project marker discovery"
assert_eq "$v11_project/04_Revisions/Revision_01" "$(jl_context_revision_root_v11 "$v11_project/04_Revisions/Revision_01/sub")" "v1.1 revision boundary discovery"
assert_eq "$v11_project/04_Revisions/Revision_01" "$(jl_context_revision_root_for_number "$v11_project" 1)" "v1.1 numbered revision path"
assert_eq "$v11_project/05_Final_Delivery" "$(jl_context_delivery_root_v11 "$v11_project")" "v1.1 delivery boundary"

legacy="$tmp/legacy"
mkdir -p "$legacy/Studio" "$legacy/Clients/Acme/Projects/Active/Blue Sky"
cat > "$legacy/Studio/studio.json" <<'EOF_LEGACY'
{"metadata":{"schema":"mixing-studio","schema_version":"1.0.4"}}
EOF_LEGACY
assert_failure "legacy schema rejected" jl_context_require_v11_workspace "$legacy"
mkdir -p "$legacy/DAWs"
assert_failure "legacy directory layout rejected" jl_context_reject_legacy_layout "$legacy"

echo "[OK] context.sh ($TEST_COUNT assertions)"
