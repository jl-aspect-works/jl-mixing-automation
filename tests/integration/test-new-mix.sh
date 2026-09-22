#!/usr/bin/env bash
set -eu

# Purpose: Exercise the complete v1.2 project-creation contract.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=tests/integration/integration-helper.sh
. "$ROOT/tests/integration/integration-helper.sh"
expected_created_with="jl-mixing $(cat "$ROOT/VERSION")"

require_test_command jq
require_test_command python3
python3 -c 'import jsonschema' >/dev/null 2>&1 || {
    if [ "${JL_TEST_STRICT:-0}" = "1" ]; then
        fail "jsonschema is required for strict new-mix tests"
    fi
    echo "[SKIP] new-mix integration tests require jsonschema."
    exit 0
}

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
studio_root="$tmp/studio"

"$ROOT/bin/new-studio" \
    --root "$studio_root" --name "JL Mix Studio" --engineer "Jake" >/dev/null
JL_MIXING_ROOT="$studio_root" "$ROOT/bin/new-client" acme \
    --name "Acme Records" --artist "The Acmes" >/dev/null
client_root="$studio_root/Clients/Acme Records"
client_file="$client_root/client.json"

run_project() {
    JL_MIXING_ROOT="$studio_root" "$ROOT/bin/new-mix" "$@"
}

# A project created from client context uses readable flattened paths, strict
# v1.1-schema manifests, minimal Markdown templates, an initial revision, and a
# recursive immutable source import without creating a delivery manifest.
mkdir -p "$tmp/source/Audio/Drums" "$tmp/source/Documentation/Empty Folder"
printf 'kick audio\n' > "$tmp/source/Audio/Drums/Kick.wav"
printf 'session notes\n' > "$tmp/source/Documentation/notes.txt"
output="$(cd "$client_root" && "$ROOT/bin/new-mix" \
    'Blue Sky / Radio Mix' \
    --project-id blue-sky-radio \
    --album 'Blue Sky Album' \
    --producer 'Pat Producer' \
    --engineer 'Morgan Mixer' \
    --bpm 122.5 \
    --key 'D minor' \
    --time-signature '6/8' \
    --sample-rate 96000 \
    --bit-depth 32 \
    --file-format aiff \
    --deadline 2026-12-31 \
    --deliverables 'stems, main_mix' \
    --description 'Wide, punchy, vocal-forward mix' \
    --source "$tmp/source")"
project_root="$client_root/Projects/Blue Sky - Radio Mix"
manifest="$project_root/00_Admin/project-manifest.json"
snapshot="$project_root/00_Admin/client-profile-snapshot.json"

assert_dir_exists "$project_root"
assert_dir_exists "$project_root/03_DAW_Project"
assert_path_not_exists "$project_root/03_DAW_Project/Project"
assert_dir_exists "$project_root/04_Revisions/Revision_01"
assert_file_exists "$project_root/04_Revisions/Revision_01/Revision_Notes.md"
assert_path_not_exists "$project_root/04_Revisions/Revision_01/Prints"
assert_contains "$(cat "$project_root/04_Revisions/Revision_01/Revision_Notes.md")" \
    '# Revision 1 Notes' "initial revision heading"
assert_contains "$(cat "$project_root/04_Revisions/Revision_01/Revision_Notes.md")" \
    'Description: Initial mix' "initial revision description"
assert_dir_exists "$project_root/05_Final_Delivery/Stems"
assert_path_not_exists "$project_root/05_Final_Delivery/delivery-manifest.json"
assert_file_exists "$manifest"
assert_file_exists "$snapshot"
assert_file_exists "$project_root/00_Admin/Intake_Report.md"
assert_file_exists "$project_root/00_Admin/Project_Notes.md"
assert_file_exists "$project_root/02_Audio_Preparation/Preparation_Report.md"
assert_file_exists "$project_root/05_Final_Delivery/Delivery_Notes.md"
assert_file_exists "$project_root/06_Recall/Recall_Sheet.md"
assert_same_bytes "$ROOT/templates/Intake_Report.md" "$project_root/00_Admin/Intake_Report.md"
assert_same_bytes "$ROOT/templates/Project_Notes.md" "$project_root/00_Admin/Project_Notes.md"
assert_same_bytes "$ROOT/templates/Preparation_Report.md" "$project_root/02_Audio_Preparation/Preparation_Report.md"
assert_same_bytes "$ROOT/templates/Delivery_Notes.md" "$project_root/05_Final_Delivery/Delivery_Notes.md"
assert_same_bytes "$ROOT/templates/Recall_Sheet.md" "$project_root/06_Recall/Recall_Sheet.md"
assert_file_exists "$project_root/01_Client_Files/Original_Delivery/Audio/Drums/Kick.wav"
assert_file_exists "$project_root/01_Client_Files/Original_Delivery/Documentation/notes.txt"
assert_dir_exists "$project_root/01_Client_Files/Original_Delivery/Documentation/Empty Folder"
assert_same_bytes "$tmp/source/Audio/Drums/Kick.wav" \
    "$project_root/01_Client_Files/Original_Delivery/Audio/Drums/Kick.wav"
assert_file_exists "$tmp/source/Audio/Drums/Kick.wav"

assert_json_eq "mixing-project" "$manifest" '.metadata.schema' "project schema identity"
assert_json_eq "1.1.0" "$manifest" '.metadata.schema_version' "project schema version"
assert_json_eq "$expected_created_with" "$manifest" '.metadata.created_with' \
    "project creator release"
assert_json_eq "blue-sky-radio" "$manifest" '.project_id' "explicit project ID"
assert_json_eq 'Blue Sky / Radio Mix' "$manifest" '.project_name' "display name preserved"
assert_json_eq 'The Acmes' "$manifest" '.artist' "client artist default"
assert_json_eq 'Blue Sky Album' "$manifest" '.album' "album override"
assert_json_eq 'Pat Producer' "$manifest" '.producer' "producer override"
assert_json_eq 'Morgan Mixer' "$manifest" '.mix_engineer' "engineer override"
assert_json_eq '122.5' "$manifest" '.music.bpm' "BPM override"
assert_json_eq 'D minor' "$manifest" '.music.key' "key override"
assert_json_eq '6/8' "$manifest" '.music.time_signature' "time-signature override"
assert_json_eq '96000' "$manifest" '.audio.sample_rate' "sample-rate override"
assert_json_eq '32' "$manifest" '.audio.bit_depth' "bit-depth override"
assert_json_eq 'AIFF' "$manifest" '.audio.file_format' "file-format normalization"
assert_eq '["stems","main_mix"]' \
    "$(jq -c '.delivery.requested_deliverables' "$manifest")" \
    "requested deliverable order preserved"
assert_json_eq '2026-12-31' "$manifest" '.schedule.deadline' "deadline override"
assert_json_eq 'Wide, punchy, vocal-forward mix' "$manifest" '.creative_direction' \
    "creative direction"
assert_eq '{"current_revision":1,"approved_revision":null,"delivered_revision":null}' \
    "$(jq -c '.state' "$manifest")" "initial three-pointer state"
assert_eq '1' "$(jq -r '.revisions | length' "$manifest")" "one initial revision record"
assert_json_eq '1' "$manifest" '.revisions[0].number' "initial revision number"
assert_json_eq 'Initial mix' "$manifest" '.revisions[0].description' \
    "initial revision description stored"
assert_eq 'null' "$(jq -c '.revisions[0].approval.approved_at' "$manifest")" \
    "initial revision approval date is null"
assert_eq 'null' "$(jq -c '.revisions[0].approval.approved_by' "$manifest")" \
    "initial revision approver is null"
assert_eq "false" "$(jq -r 'has("project_type") or has("daw")' "$manifest")" \
    "removed project and DAW metadata absent"
assert_json_eq 'mixing-client-profile-snapshot' "$snapshot" '.metadata.schema' \
    "snapshot schema identity"
assert_json_eq "$expected_created_with" "$snapshot" '.metadata.created_with' \
    "snapshot creator release"
assert_eq "$(jq -c '.defaults' "$client_file")" "$(jq -c '.defaults' "$snapshot")" \
    "client defaults copied exactly into snapshot"
assert_json_eq "$(jq -r '.metadata.document_id' "$client_file")" "$snapshot" \
    '.source_client.client_document_id' "snapshot client document reference"
project_document_id="$(jq -r '.metadata.document_id' "$manifest")"
snapshot_document_id="$(jq -r '.metadata.document_id' "$snapshot")"
revision_id="$(jq -r '.revisions[0].revision_id' "$manifest")"
[ "$project_document_id" != "$snapshot_document_id" ] || \
    fail "project and snapshot UUIDs must differ"
[ "$revision_id" != "$project_document_id" ] && [ "$revision_id" != "$snapshot_document_id" ] || \
    fail "revision UUID must differ from document UUIDs"
python3 - "$revision_id" <<'PY_UUID'
from uuid import UUID
import sys
value = UUID(sys.argv[1])
raise SystemExit(0 if value.version == 4 else 1)
PY_UUID
pass "project, snapshot, and initial revision UUIDs are valid and distinct"
python3 "$ROOT/tools/validate-json.py" --strict \
    --schema "$ROOT/schemas/project-manifest.schema.json" --document "$manifest" >/dev/null
pass "generated project validates against canonical schema"
python3 "$ROOT/tools/validate-json.py" --strict \
    --schema "$ROOT/schemas/client-profile-snapshot.schema.json" --document "$snapshot" >/dev/null
pass "generated snapshot validates against canonical schema"
assert_eq 'In progress' "$(python3 "$ROOT/tools/project-state.py" derive "$project_root")" \
    "initial derived state"
assert_contains "$output" 'Project created successfully.' "success heading"
assert_contains "$output" 'Initial revision:' "initial revision summary"
assert_contains "$output" 'approve-mix' "next approval command"
case "$output" in
    *'new-revision --description "Initial mix"'*) fail "obsolete next command was printed" ;;
    *) pass "obsolete initial new-revision command omitted" ;;
esac
assert_contains "$output" "cd '$project_root'" "copy-and-paste cd"

# Stable client-ID resolution and omitted project fields use the approved
# client/studio defaults. No 4/4 time signature is assumed.
output="$(cd "$studio_root" && "$ROOT/bin/new-mix" --client acme --project 'Default Project')"
default_root="$client_root/Projects/Default Project"
default_manifest="$default_root/00_Admin/project-manifest.json"
assert_file_exists "$default_manifest"
assert_json_eq 'default-project' "$default_manifest" '.project_id' "derived project ID"
assert_json_eq 'The Acmes' "$default_manifest" '.artist' "inherited artist"
assert_json_eq 'Jake' "$default_manifest" '.mix_engineer' "studio engineer default"
assert_eq 'null' "$(jq -c '.music.bpm' "$default_manifest")" "default BPM is null"
assert_json_eq '' "$default_manifest" '.music.key' "default key empty"
assert_json_eq '' "$default_manifest" '.music.time_signature' "no assumed time signature"
assert_json_eq '48000' "$default_manifest" '.audio.sample_rate' "client audio default"
assert_json_eq 'Cloud transfer' "$default_manifest" '.delivery.method' "client delivery method"
assert_eq 'null' "$(jq -c '.schedule.deadline' "$default_manifest")" "default deadline null"
assert_json_eq '' "$default_manifest" '.creative_direction' "default creative direction empty"
assert_contains "$output" 'Default Project' "ID-resolved project output"

# The positional project name may follow other options and uses the same project
# creation path as --project.
positional_after_output="$(run_project --client acme --artist 'Positional Artist' 'Positional After')"
positional_after_root="$client_root/Projects/Positional After"
assert_file_exists "$positional_after_root/00_Admin/project-manifest.json"
assert_json_eq 'Positional After' \
    "$positional_after_root/00_Admin/project-manifest.json" '.project_name' \
    "positional project after options"
assert_json_eq 'Positional Artist' \
    "$positional_after_root/00_Admin/project-manifest.json" '.artist' \
    "explicit artist overrides client defaults"
assert_contains "$positional_after_output" 'Positional After' \
    "positional-after-options output"
help_output="$(run_project --help)"
assert_contains "$help_output" 'new-mix PROJECT_NAME [options]' \
    "help documents positional form"
assert_contains "$help_output" 'new-mix --project PROJECT_NAME [options]' \
    "help documents option form"

# An explicit client path works from outside the workspace. Dry-run performs
# source validation and reports the complete plan without creating a project.
dry_output="$(cd "$tmp" && "$ROOT/bin/new-mix" \
    --client "$client_root/client.json" --project 'Dry Project' \
    --source "$tmp/source" --dry-run)"
assert_contains "$dry_output" 'Dry run — no changes made.' "dry-run heading"
assert_contains "$dry_output" '03_DAW_Project/' "dry-run flattened DAW boundary"
assert_contains "$dry_output" 'Audio/Drums/Kick.wav' "dry-run source plan"
assert_contains "$dry_output" 'Initial state:              In progress' "dry-run state"
assert_contains "$dry_output" 'Current revision:           1' "dry-run revision pointer"
assert_contains "$dry_output" '04_Revisions/Revision_01/Revision_Notes.md' \
    "dry-run initial revision plan"
assert_contains "$dry_output" 'approve-mix' "dry-run next step"
case "$dry_output" in
    *'new-revision --description "Initial mix"'*) fail "dry-run printed obsolete next command" ;;
    *) pass "dry-run omits obsolete initial new-revision command" ;;
esac
assert_path_not_exists "$client_root/Projects/Dry Project"

# Project IDs and readable destination folders are independently protected
# against case-insensitive collisions without automatic suffixes.
assert_failure "duplicate project ID is protected" \
    run_project --client acme --project 'Different Name' --project-id blue-sky-radio
assert_failure "case-insensitive project folder collision is protected" \
    run_project --client acme --project 'DEFAULT PROJECT' --project-id another-id
assert_path_not_exists "$client_root/Projects/Different Name"

# Explicit validation failures occur before any project filesystem mutation.
assert_failure "missing project name rejected" run_project --client acme
assert_failure "empty option project name rejected" run_project --client acme --project ''
assert_failure "empty positional project name rejected" run_project --client acme ''
assert_failure "positional then option project rejected" \
    run_project 'Both Forms One' --client acme --project 'Both Forms Two'
assert_failure "option then positional project rejected" \
    run_project --client acme --project 'Both Forms One' 'Both Forms Two'
assert_failure "additional positional argument rejected" \
    run_project --client acme 'One Position' 'Two Position'
assert_path_not_exists "$client_root/Projects/Both Forms One"
assert_path_not_exists "$client_root/Projects/One Position"
assert_failure "invalid explicit project ID rejected" \
    run_project --client acme --project Bad --project-id Bad_ID
assert_failure "nonpositive BPM rejected" run_project --client acme --project BadBpm --bpm 0
assert_failure "invalid calendar deadline rejected" \
    run_project --client acme --project BadDate --deadline 2026-02-30
assert_failure "unsupported sample rate rejected" \
    run_project --client acme --project BadRate --sample-rate 22050
assert_failure "empty deliverables rejected" \
    run_project --client acme --project NoDeliverables --deliverables ''
assert_failure "duplicate deliverables rejected" \
    run_project --client acme --project DuplicateTypes --deliverables 'stems,stems'
assert_failure "unsupported deliverable rejected" \
    run_project --client acme --project BadType --deliverables 'main_mix,other'
assert_failure "unknown client ID rejected" \
    run_project --client missing-client --project MissingClient
assert_path_not_exists "$client_root/Projects/BadBpm"

# Removed v1.0 options provide targeted migration diagnostics.
for removed_option in --project-type --daw --template --non-interactive; do
    set +e
    removed_output="$(run_project --client acme --project Removed "$removed_option" value 2>&1)"
    removed_status=$?
    set -e
    [ "$removed_status" -ne 0 ] || fail "$removed_option unexpectedly succeeded"
    assert_contains "$removed_output" "$removed_option was removed in JL Mixing 1.1." \
        "$removed_option diagnostic"
done

# Source imports reject symlinks and case-insensitive collisions before the
# project transaction begins.
ln -s "$tmp/source/Audio/Drums/Kick.wav" "$tmp/source/linked-kick.wav"
assert_failure "nested source symlink rejected" \
    run_project --client acme --project SymlinkSource --source "$tmp/source"
assert_path_not_exists "$client_root/Projects/SymlinkSource"
rm "$tmp/source/linked-kick.wav"

case_source="$tmp/case-source"
mkdir -p "$case_source"
printf A > "$case_source/Print.wav"
printf B > "$case_source/print.wav" 2>/dev/null || true
if [ -f "$case_source/Print.wav" ] && [ -f "$case_source/print.wav" ] && \
   [ "$(cat "$case_source/Print.wav")" != "$(cat "$case_source/print.wav")" ]; then
    assert_failure "case-insensitive source collision rejected" \
        run_project --client acme --project CaseSource --source "$case_source"
else
    pass "case-insensitive source collision fixture unavailable on this filesystem"
fi
assert_path_not_exists "$client_root/Projects/CaseSource"

# Empty client artist defaults fall back to the client display name without
# rewriting the immutable client snapshot. Explicit empty overrides remain invalid.
client_backup="$tmp/client-backup.json"
cp "$client_file" "$client_backup"
jq '.defaults.artist=""' "$client_file" > "$client_file.tmp"
mv "$client_file.tmp" "$client_file"
fallback_output="$(run_project --client acme 'Client Name Artist')"
fallback_root="$client_root/Projects/Client Name Artist"
fallback_manifest="$fallback_root/00_Admin/project-manifest.json"
fallback_snapshot="$fallback_root/00_Admin/client-profile-snapshot.json"
assert_json_eq 'Acme Records' "$fallback_manifest" '.artist' \
    "client name artist fallback"
assert_json_eq '' "$fallback_snapshot" '.defaults.artist' \
    "snapshot preserves empty client artist default"
assert_contains "$fallback_output" 'Artist:                     Acme Records' \
    "resolved fallback artist reported"
fallback_dry_output="$(run_project --client acme 'Client Name Artist Dry' --dry-run)"
assert_contains "$fallback_dry_output" 'Artist:                     Acme Records' \
    "dry-run reports client name artist fallback"
assert_failure "explicit empty artist rejected" \
    run_project --client acme 'Explicit Empty Artist' --artist ''
assert_path_not_exists "$client_root/Projects/Explicit Empty Artist"
cp "$client_backup" "$client_file"

# Directory-changing behavior uses the secure private result channel only
# after commit and falls back to a quoted command when integration is absent.
cd_result="$tmp/cd-result"
: > "$cd_result"
chmod 600 "$cd_result"
cd_output="$(JL_MIXING_CD_RESULT_FILE="$cd_result" \
    run_project --client acme --project 'Cd Project' --cd)"
cd_root="$client_root/Projects/Cd Project"
assert_eq "$cd_root" "$(cat "$cd_result")" "explicit cd result path"
case "$cd_output" in
    *"cd '$cd_root'"*) fail "successful result channel printed redundant cd command" ;;
    *) pass "successful result channel omits redundant cd command" ;;
esac

fallback_output="$(run_project --client acme --project 'Fallback Project' --cd)"
fallback_root="$client_root/Projects/Fallback Project"
assert_contains "$fallback_output" 'integration is not active.' "missing integration warning"
assert_contains "$fallback_output" "cd '$fallback_root'" "fallback cd command"

# The studio default can request directory changing, while --no-cd overrides
# it for one command.
jq '.cli.change_directory_after_create=true' "$studio_root/Studio/studio.json" \
    > "$studio_root/Studio/studio.json.tmp"
mv "$studio_root/Studio/studio.json.tmp" "$studio_root/Studio/studio.json"
: > "$cd_result"
JL_MIXING_CD_RESULT_FILE="$cd_result" \
    run_project --client acme --project 'Default Cd Project' >/dev/null
assert_eq "$client_root/Projects/Default Cd Project" "$(cat "$cd_result")" \
    "studio default cd result"
: > "$cd_result"
JL_MIXING_CD_RESULT_FILE="$cd_result" \
    run_project --client acme --project 'No Cd Project' --no-cd >/dev/null
assert_eq '' "$(cat "$cd_result")" "explicit no-cd overrides studio default"
assert_failure "--cd and --no-cd are mutually exclusive" \
    run_project --client acme --project ConflictingCd --cd --no-cd
assert_failure "--cd is incompatible with dry-run" \
    run_project --client acme --project DryCd --cd --dry-run

# A failure after the staged directory rename removes only the new project and
# leaves all previously committed projects and source files untouched.
assert_failure "injected commit failure rolls back project" \
    env JL_MIXING_ROOT="$studio_root" JL_MIXING_FAIL_AT=after-directory-commit \
        "$ROOT/bin/new-mix" --client acme --project 'Rollback Project' \
        --source "$tmp/source"
assert_path_not_exists "$client_root/Projects/Rollback Project"
assert_file_exists "$manifest"
assert_file_exists "$tmp/source/Audio/Drums/Kick.wav"

# Recognizable v1.0 workspaces are rejected without modification.
legacy_root="$tmp/legacy-studio"
fixture_studio "$legacy_root"
assert_failure "legacy workspace rejected" \
    env JL_MIXING_ROOT="$legacy_root" "$ROOT/bin/new-mix" \
        --client acme --project LegacyProject --artist Artist

printf '[OK] new-mix (%s assertions)\n' "$TEST_COUNT"
