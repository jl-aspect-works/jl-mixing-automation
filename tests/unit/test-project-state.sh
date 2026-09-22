#!/usr/bin/env bash
set -eu

# Purpose: Verify v1.1 pointer validation and derived workflow/revision states.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
require_test_command jq
. "$ROOT/lib/project-state.sh"

# Arrange: build a minimal canonical v1.1 project without relying on Phase 2 schemas.
tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT
project="$tmp/Blue Sky"
manifest="$project/00_Admin/project-manifest.json"
mkdir -p "$project/00_Admin" "$project/04_Revisions" "$project/05_Final_Delivery"

write_manifest() {
    revisions_json="$1"
    current="$2"
    approved_json="$3"
    delivered_json="$4"
    jq -n \
        --argjson revisions "$revisions_json" \
        --argjson current "$current" \
        --argjson approved "$approved_json" \
        --argjson delivered "$delivered_json" \
        '{
          metadata: {
            schema: "mixing-project",
            schema_version: "1.1.0",
            document_id: "44444444-4444-4444-8444-444444444444",
            created_with: "jl-mixing 1.1.0",
            created_at: "2026-07-14T20:00:00Z",
            last_modified_at: "2026-07-14T20:00:00Z"
          },
          project_id: "blue-sky",
          project_name: "Blue Sky",
          client: {
            client_document_id: "22222222-2222-4222-8222-222222222222",
            client_id: "acme"
          },
          delivery: {method: "Cloud transfer", requested_deliverables: ["main_mix"]},
          state: {
            current_revision: $current,
            approved_revision: $approved,
            delivered_revision: $delivered
          },
          revisions: $revisions
        }' > "$manifest"
}

revision_one_unapproved='[
  {
    "number": 1,
    "revision_id": "55555555-5555-4555-8555-555555555551",
    "created_at": "2026-07-15T10:00:00Z",
    "description": "Initial mix",
    "approval": {"approved_at": null, "approved_by": null}
  }
]'
revision_one_approved='[
  {
    "number": 1,
    "revision_id": "55555555-5555-4555-8555-555555555551",
    "created_at": "2026-07-15T10:00:00Z",
    "description": "Initial mix",
    "approval": {"approved_at": "2026-07-15T12:00:00Z", "approved_by": "Client"}
  }
]'

write_manifest '[]' 0 null null
assert_eq "Setup" "$(jl_project_state_derive "$project")" "Setup stage derived"

mkdir "$project/04_Revisions/Revision_01"
write_manifest "$revision_one_unapproved" 1 null null
assert_eq "In progress" "$(jl_project_state_derive "$project")" "In-progress stage derived"
assert_eq "open" "$(jl_project_revision_status "$manifest" 1)" "current unapproved revision is open"

write_manifest "$revision_one_approved" 1 1 null
assert_eq "Approved" "$(jl_project_state_derive "$project")" "Approved stage derived"
assert_eq "approved" "$(jl_project_revision_status "$manifest" 1)" "approved revision status derived"

printf 'mix' > "$project/05_Final_Delivery/Blue Sky Main Mix.wav"
cat > "$project/05_Final_Delivery/delivery-manifest.json" <<'EOF_DELIVERY'
{
  "metadata": {
    "schema": "mixing-delivery",
    "schema_version": "1.1.0",
    "document_id": "66666666-6666-4666-8666-666666666666",
    "created_with": "jl-mixing 1.1.0",
    "created_at": "2026-07-15T13:00:00Z"
  },
  "project": {
    "project_document_id": "44444444-4444-4444-8444-444444444444",
    "project_id": "blue-sky",
    "project_name": "Blue Sky"
  },
  "client": {
    "client_document_id": "22222222-2222-4222-8222-222222222222",
    "client_id": "acme"
  },
  "revision": {
    "number": 1,
    "revision_id": "55555555-5555-4555-8555-555555555551",
    "description": "Initial mix",
    "approval": {"approved_at": "2026-07-15T12:00:00Z", "approved_by": "Client"}
  },
  "delivery": {"method": "Cloud transfer"},
  "files": [
    {
      "path": "Blue Sky Main Mix.wav",
      "deliverable_type": "main_mix",
      "size_bytes": 3,
      "sha256": "1111111111111111111111111111111111111111111111111111111111111111"
    }
  ]
}
EOF_DELIVERY
write_manifest "$revision_one_approved" 1 1 1
assert_eq "Delivered" "$(jl_project_state_derive "$project")" "Delivered stage derived"

mkdir "$project/04_Revisions/Revision_02"
revision_two='[
  {
    "number": 1,
    "revision_id": "55555555-5555-4555-8555-555555555551",
    "created_at": "2026-07-15T10:00:00Z",
    "description": "Initial mix",
    "approval": {"approved_at": "2026-07-15T12:00:00Z", "approved_by": "Client"}
  },
  {
    "number": 2,
    "revision_id": "55555555-5555-4555-8555-555555555552",
    "created_at": "2026-07-16T10:00:00Z",
    "description": "Client changes",
    "approval": {"approved_at": null, "approved_by": null}
  }
]'
write_manifest "$revision_two" 2 1 1
assert_eq "In progress" "$(jl_project_state_derive "$project")" "newer work returns project to In progress"
assert_eq "approved" "$(jl_project_revision_status "$manifest" 1)" "older approved revision remains approved"
assert_eq "open" "$(jl_project_revision_status "$manifest" 2)" "new current revision is open"

# Delivery approval is an immutable package-time snapshot. Reapproving the same
# delivered revision may replace the project record without rewriting the
# existing delivery manifest.
jq '.revisions[0].approval = {approved_at:"2026-07-17T12:00:00Z", approved_by:"Label"}' \
    "$manifest" > "$tmp/reapproved.json"
mv "$tmp/reapproved.json" "$manifest"
assert_eq "In progress" "$(jl_project_state_derive "$project")" \
    "delivery approval snapshot may differ after reapproval"
write_manifest "$revision_two" 2 1 1

# Invalid state fixtures fail without silently repairing records or directories.
jq '.revisions[1].number = 3' "$manifest" > "$tmp/noncontiguous.json"
assert_failure "noncontiguous revisions rejected" \
    jl_project_validate_revision_records "$tmp/noncontiguous.json"
jq '.revisions[1].approval.approved_at = "2026-07-16T12:00:00Z"' "$manifest" > "$tmp/unpaired.json"
assert_failure "unpaired approval fields rejected" \
    jl_project_validate_revision_records "$tmp/unpaired.json"
jq '.metadata.created_with = "jl-mixing 1.2.0"' "$manifest" > "$tmp/v12-created-with.json"
cp "$tmp/v12-created-with.json" "$manifest"
assert_success "project creator release is independent of schema version" \
    jl_project_validate_state "$project"
jq '.metadata.created_with = "jl-mixing 1.2"' "$manifest" > "$tmp/wrong-created-with.json"
cp "$tmp/wrong-created-with.json" "$manifest"
assert_failure "malformed project creator release rejected" \
    jl_project_validate_state "$project"
write_manifest "$revision_two" 2 1 1
rm -f "$project/05_Final_Delivery/delivery-manifest.json"
assert_failure "delivered pointer without manifest rejected" \
    jl_project_validate_delivery_consistency "$project"

# Restore pointer to null and verify an untracked manifest is also invalid.
write_manifest "$revision_two" 2 1 null
printf '{}\n' > "$project/05_Final_Delivery/delivery-manifest.json"
assert_failure "delivery manifest without pointer rejected" \
    jl_project_validate_delivery_consistency "$project"

echo "[OK] project-state.sh ($TEST_COUNT assertions)"
