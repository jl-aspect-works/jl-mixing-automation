#!/usr/bin/env bash
set -eu

# Purpose: Exercise v1.1 approval, historical metadata, older revisions, and warnings.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/integration/integration-helper.sh"

require_test_command jq
require_test_command python3
python3 -c 'import jsonschema' >/dev/null 2>&1 || {
    if [ "${JL_TEST_STRICT:-0}" = "1" ]; then
        fail "jsonschema is required for strict approve-mix tests"
    fi
    echo "[SKIP] approve-mix integration tests require jsonschema."
    exit 0
}

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
studio_root="$tmp/studio"
project_root="$(fixture_v11_project "$studio_root")"
manifest="$project_root/00_Admin/project-manifest.json"
(cd "$project_root" && "$ROOT/bin/new-revision" --description 'Initial mix' >/dev/null)
(cd "$project_root" && "$ROOT/bin/new-revision" --description 'Second mix' >/dev/null)

run_approve() {
    (cd "$project_root/04_Revisions/Revision_02" && "$ROOT/bin/approve-mix" "$@")
}

# Omitted revision defaults to current; approver defaults to Client.
output="$(run_approve --date 2030-01-01T12:00:00Z)"
assert_json_eq "2" "$manifest" '.state.approved_revision' "current revision approved"
assert_json_eq "2" "$manifest" '.state.current_revision' "current pointer unchanged"
assert_eq "null" "$(jq -c '.state.delivered_revision' "$manifest")" \
    "delivered pointer unchanged"
assert_json_eq "Client" "$manifest" '.revisions[1].approval.approved_by' \
    "default approver stored"
assert_json_eq "2030-01-01T12:00:00Z" "$manifest" \
    '.revisions[1].approval.approved_at' "approval timestamp stored"
assert_eq "null" "$(jq -c '.revisions[0].approval.approved_at' "$manifest")" \
    "unselected revision remains unapproved"
assert_contains "$output" 'Project state:               Approved' "approved state output"
assert_contains "$output" 'create-delivery' "delivery next step"

# New work preserves the prior approval and returns the project to In progress.
(cd "$project_root" && "$ROOT/bin/new-revision" --description 'Third mix' >/dev/null)
assert_json_eq "3" "$manifest" '.state.current_revision' "new revision becomes current"
assert_json_eq "2" "$manifest" '.state.approved_revision' "prior approval pointer preserved"
assert_json_eq "Client" "$manifest" '.revisions[1].approval.approved_by' \
    "historical approval retained after new revision"
assert_eq "In progress" "$(python3 "$ROOT/tools/project-state.py" derive "$project_root")" \
    "new work derives In progress"

# Build a structurally valid current delivery for Revision 2 so approval output
# can verify the explicit replacement warning without relying on create-delivery.
printf 'mix' > "$project_root/05_Final_Delivery/Blue Sky Main.wav"
project_document_id="$(jq -r '.metadata.document_id' "$manifest")"
project_id="$(jq -r '.project_id' "$manifest")"
project_name="$(jq -r '.project_name' "$manifest")"
client_document_id="$(jq -r '.client.client_document_id' "$manifest")"
client_id="$(jq -r '.client.client_id' "$manifest")"
revision_two_id="$(jq -r '.revisions[1].revision_id' "$manifest")"
revision_two_description="$(jq -r '.revisions[1].description' "$manifest")"
revision_two_approval="$(jq -c '.revisions[1].approval' "$manifest")"
delivery_method="$(jq -r '.delivery.method' "$manifest")"
jq -n \
    --arg project_document_id "$project_document_id" \
    --arg project_id "$project_id" \
    --arg project_name "$project_name" \
    --arg client_document_id "$client_document_id" \
    --arg client_id "$client_id" \
    --arg revision_id "$revision_two_id" \
    --arg description "$revision_two_description" \
    --argjson approval "$revision_two_approval" \
    --arg method "$delivery_method" \
    '{
      metadata:{schema:"mixing-delivery",schema_version:"1.1.0",
        document_id:"77777777-7777-4777-8777-777777777777",
        created_with:"jl-mixing 1.1.0",created_at:"2030-01-01T13:00:00Z"},
      project:{project_document_id:$project_document_id,project_id:$project_id,project_name:$project_name},
      client:{client_document_id:$client_document_id,client_id:$client_id},
      revision:{number:2,revision_id:$revision_id,description:$description,approval:$approval},
      delivery:{method:$method},
      files:[{path:"Blue Sky Main.wav",deliverable_type:"main_mix",size_bytes:3,
        sha256:"1111111111111111111111111111111111111111111111111111111111111111"}]
    }' > "$project_root/05_Final_Delivery/delivery-manifest.json"
jq '.state.delivered_revision=2' "$manifest" > "$manifest.tmp"
mv "$manifest.tmp" "$manifest"

# Approving an older revision is valid, retains Revision 2 history, and warns
# that final delivery still represents another revision.
output="$(run_approve --revision 1 --approved-by Producer --date 2030-01-02T12:00:00Z)"
assert_json_eq "1" "$manifest" '.state.approved_revision' "approval moved backward"
assert_json_eq "Producer" "$manifest" '.revisions[0].approval.approved_by' \
    "older revision approval stored"
assert_json_eq "Client" "$manifest" '.revisions[1].approval.approved_by' \
    "prior revision approval retained historically"
assert_json_eq "2" "$manifest" '.state.delivered_revision' "delivery pointer preserved"
assert_contains "$output" 'older than the current working revision' "older-revision notice"
assert_contains "$output" 'Current final delivery represents Revision 2.' \
    "delivery replacement warning"
assert_contains "$output" 'Project state:               In progress' "older approval state"

# Reapproving a previously approved but currently unapproved revision replaces
# only that revision's approval metadata.
output="$(run_approve --revision 2 --approved-by Label --date 2030-01-03T12:00:00Z)"
assert_json_eq "2" "$manifest" '.state.approved_revision' "approval returned to revision two"
assert_json_eq "Label" "$manifest" '.revisions[1].approval.approved_by' \
    "revision two approval metadata replaced"
assert_json_eq "Producer" "$manifest" '.revisions[0].approval.approved_by' \
    "revision one historical metadata retained"
case "$output" in
    *'Current final delivery represents Revision'*) fail "matching delivered revision warned unexpectedly" ;;
    *) pass "matching delivered revision produces no replacement warning" ;;
esac

# Already-approved is a no-op error and leaves the manifest byte-identical.
cp "$manifest" "$tmp/no-op-before.json"
set +e
no_op_output="$(run_approve --revision 2 --approved-by SomeoneElse 2>&1)"
no_op_status=$?
set -e
[ "$no_op_status" -ne 0 ] || fail "already-approved revision unexpectedly succeeded"
pass "already-approved revision rejected"
assert_contains "$no_op_output" 'already the approved revision' "no-op diagnostic"
assert_contains "$no_op_output" 'create-delivery' "no-op next guidance"
assert_same_bytes "$tmp/no-op-before.json" "$manifest"

# Dry-run previews approval without generating or persisting a timestamp.
dry_output="$(run_approve --revision 3 --dry-run)"
assert_contains "$dry_output" 'current time at execution' "dry-run timestamp description"
assert_contains "$dry_output" 'state.approved_revision: 2 → 3' "dry-run pointer change"
assert_json_eq "2" "$manifest" '.state.approved_revision' "dry-run leaves approval unchanged"

# Validation and removed-option failures make no changes.
assert_failure "approval date before revision creation rejected" \
    run_approve --revision 3 --date 2000-01-01T00:00:00Z
assert_failure "timezone-free approval date rejected" \
    run_approve --revision 3 --date 2030-01-04T12:00:00
assert_failure "empty approver rejected" run_approve --revision 3 --approved-by ''
assert_failure "missing revision rejected" run_approve --revision 99
assert_failure "removed notes option rejected" run_approve --notes 'Approved'
assert_failure "removed non-interactive option rejected" run_approve --non-interactive
assert_json_eq "2" "$manifest" '.state.approved_revision' "validation failures preserve approval"

# Failure after file replacement is rolled back to the exact prior manifest.
cp "$manifest" "$tmp/rollback-before.json"
assert_failure "approval transaction failure rolls back" \
    env JL_MIXING_FAIL_AT=after-file-replacement \
        JL_MIXING_HOME="$ROOT" JL_MIXING_ROOT="$studio_root" \
        "$ROOT/bin/approve-mix" --project "$project_root" --revision 3 \
        --approved-by Client --date 2030-01-05T12:00:00Z
assert_same_bytes "$tmp/rollback-before.json" "$manifest"

echo "[OK] approve-mix ($TEST_COUNT assertions)"
