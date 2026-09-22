#!/usr/bin/env bash
set -eu

# Purpose: Verify canonical v1.1 revision records and pointer mutations.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
require_test_command jq
. "$ROOT/lib/revision.sh"

# Arrange: build a canonical v1.1 manifest with one unapproved revision.
tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
manifest="$tmp/project.json"
jq '.state={current_revision:1,approved_revision:null,delivered_revision:null} |
    .revisions=[.revisions[0] | .approval={approved_at:null,approved_by:null}]' \
    "$ROOT/examples/project-manifest.json" > "$manifest"

assert_eq "2" "$(jl_revision_next_number "$manifest")" "next revision follows current pointer"
record="$(jl_revision_create_record \
    2 'Vocal changes' 66666666-6666-4666-8666-666666666666 2026-07-19T12:00:00Z)"
assert_eq "2" "$(printf '%s' "$record" | jq -r '.number')" "record number"
assert_eq "Vocal changes" "$(printf '%s' "$record" | jq -r '.description')" "record description"
assert_eq "null" "$(printf '%s' "$record" | jq -c '.approval.approved_at')" "new approval timestamp null"
assert_eq "null" "$(printf '%s' "$record" | jq -c '.approval.approved_by')" "new approver null"
assert_eq "false" "$(printf '%s' "$record" | jq -r 'has("status") or has("folder") or has("created_by")')" \
    "legacy revision fields absent"

jl_revision_append "$manifest" 'Vocal changes' 2 \
    2026-07-19T12:00:00Z 66666666-6666-4666-8666-666666666666
assert_eq "2" "$(jl_revision_current "$manifest")" "append updates current revision"
assert_eq "null" "$(jq -c '.state.approved_revision' "$manifest")" "append preserves approved pointer"
assert_eq "null" "$(jq -c '.state.delivered_revision' "$manifest")" "append preserves delivered pointer"
assert_eq "open" "$(jl_revision_status "$manifest" 2)" "appended revision is open"
assert_eq "superseded" "$(jl_revision_status "$manifest" 1)" "older unapproved revision is superseded"

jl_revision_approve "$manifest" 2 Client 2026-07-20T12:00:00Z
assert_eq "approved" "$(jl_revision_status "$manifest" 2)" "selected revision approved"
assert_eq "2" "$(jl_json_get "$manifest" '.state.approved_revision')" "approved pointer"
assert_eq "Client" "$(jq -r '.revisions[1].approval.approved_by' "$manifest")" "approver stored on revision"
assert_eq "null" "$(jq -c '.state.delivered_revision' "$manifest")" "approval preserves delivery pointer"

# Moving approval retains historical metadata on the previously approved record.
jl_revision_approve "$manifest" 1 Producer 2026-07-21T12:00:00Z
assert_eq "1" "$(jl_json_get "$manifest" '.state.approved_revision')" "approval pointer moved backward"
assert_eq "Producer" "$(jq -r '.revisions[0].approval.approved_by' "$manifest")" "older revision approved"
assert_eq "Client" "$(jq -r '.revisions[1].approval.approved_by' "$manifest")" \
    "historical approval retained"
assert_failure "approving current approved revision is rejected" \
    jl_revision_approve "$manifest" 1 Client 2026-07-22T12:00:00Z


echo "[OK] revision.sh ($TEST_COUNT assertions)"
