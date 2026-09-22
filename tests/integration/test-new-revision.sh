#!/usr/bin/env bash
set -eu

# Purpose: Exercise v1.1-project compatibility and v1.2 revision creation.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/integration/integration-helper.sh"
. "$ROOT/lib/project-state.sh"

require_test_command jq
require_test_command python3
python3 -c 'import jsonschema' >/dev/null 2>&1 || {
    if [ "${JL_TEST_STRICT:-0}" = "1" ]; then
        fail "jsonschema is required for strict new-revision tests"
    fi
    echo "[SKIP] new-revision integration tests require jsonschema."
    exit 0
}

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
studio_root="$tmp/studio"
project_root="$(fixture_v11_project "$studio_root")"
manifest="$project_root/00_Admin/project-manifest.json"

run_revision() {
    (cd "$project_root" && "$ROOT/bin/new-revision" "$@")
}

# Revision 1 uses the initial-mix default and creates no Prints subdirectory.
output="$(run_revision)"
revision_one="$project_root/04_Revisions/Revision_01"
assert_dir_exists "$revision_one"
assert_file_exists "$revision_one/Revision_Notes.md"
assert_path_not_exists "$revision_one/Prints"
assert_contains "$(cat "$revision_one/Revision_Notes.md")" '# Revision 1 Notes' \
    "revision heading rendered"
assert_contains "$(cat "$revision_one/Revision_Notes.md")" 'Description: Initial mix' \
    "initial description rendered"
assert_json_eq "1" "$manifest" '.state.current_revision' "current revision advanced"
assert_eq "null" "$(jq -c '.state.approved_revision' "$manifest")" "approved pointer preserved"
assert_eq "null" "$(jq -c '.state.delivered_revision' "$manifest")" "delivered pointer preserved"
assert_json_eq "Initial mix" "$manifest" '.revisions[0].description' "default description stored"
assert_eq "null" "$(jq -c '.revisions[0].approval.approved_at' "$manifest")" \
    "new revision unapproved"
assert_eq "false" "$(jq -r '.revisions[0] | has("status") or has("folder") or has("created_by")' "$manifest")" \
    "legacy revision fields absent"
assert_contains "$output" 'Revision created successfully.' "success heading"
assert_contains "$output" 'approve-mix' "next approval command"
assert_contains "$output" "cd '$revision_one'" "copy-and-paste revision cd"
assert_eq "In progress" "$(python3 "$ROOT/tools/project-state.py" derive "$project_root")" \
    "revision creates In progress state"

# Dry-run validates and lists immediate source files without changing state.
source_dir="$tmp/revision-two-source"
mkdir "$source_dir"
printf 'main\n' > "$source_dir/Blue Sky Main.wav"
printf 'instrumental\n' > "$source_dir/Blue Sky Instrumental.wav"
dry_output="$(run_revision --description 'Client notes addressed' --source "$source_dir" --dry-run)"
assert_contains "$dry_output" 'Dry run — no changes made.' "dry-run heading"
assert_contains "$dry_output" 'Revision_02/Blue Sky Main.wav' "dry-run source file"
assert_contains "$dry_output" 'state.current_revision: 1 → 2' "dry-run state mutation"
assert_path_not_exists "$project_root/04_Revisions/Revision_02"
assert_json_eq "1" "$manifest" '.state.current_revision' "dry-run leaves manifest unchanged"

# Actual source copying preserves basenames directly in the flattened revision.
cd_result="$tmp/cd-result"
: > "$cd_result"
output="$(JL_MIXING_CD_RESULT_FILE="$cd_result" \
    run_revision --description 'Client notes addressed' --source "$source_dir" --cd)"
revision_two="$project_root/04_Revisions/Revision_02"
assert_file_exists "$revision_two/Blue Sky Main.wav"
assert_file_exists "$revision_two/Blue Sky Instrumental.wav"
assert_file_exists "$revision_two/Revision_Notes.md"
assert_path_not_exists "$revision_two/Prints"
assert_same_bytes "$source_dir/Blue Sky Main.wav" "$revision_two/Blue Sky Main.wav"
assert_eq "$revision_two" "$(cat "$cd_result")" "private directory result written"
assert_json_eq "2" "$manifest" '.state.current_revision' "second revision current"
assert_json_eq "Client notes addressed" "$manifest" '.revisions[1].description' \
    "explicit description stored"
assert_eq "superseded" "$(jl_project_revision_status "$manifest" 1)" \
    "older open revision derived superseded"
assert_eq "open" "$(jl_project_revision_status "$manifest" 2)" \
    "new current revision derived open"
case "$output" in
    *"cd '$revision_two'"*) fail "result-channel success printed redundant cd command" ;;
    *) pass "result-channel success omits redundant cd command" ;;
esac

# Later revisions receive a numbered default description and --no-cd overrides
# a studio-level automatic-directory preference.
jq '.cli.change_directory_after_create=true' "$studio_root/Studio/studio.json" \
    > "$studio_root/Studio/studio.json.tmp"
mv "$studio_root/Studio/studio.json.tmp" "$studio_root/Studio/studio.json"
output="$(run_revision --no-cd)"
revision_three="$project_root/04_Revisions/Revision_03"
assert_file_exists "$revision_three/Revision_Notes.md"
assert_json_eq "Revision 3" "$manifest" '.revisions[2].description' \
    "later default description"
assert_contains "$output" "cd '$revision_three'" "no-cd prints manual cd"

# Explicit validation failures occur before manifest or filesystem mutation.
revision_count_before="$(jq -r '.revisions | length' "$manifest")"
assert_failure "empty explicit description rejected" run_revision --description ''
assert_failure "explicit cd rejected with dry-run" run_revision --cd --dry-run
assert_failure "mutually exclusive cd options rejected" run_revision --cd --no-cd
assert_failure "removed non-interactive option rejected" run_revision --non-interactive
assert_eq "$revision_count_before" "$(jq -r '.revisions | length' "$manifest")" \
    "argument failures preserve revision history"

nested_source="$tmp/nested-source"
mkdir -p "$nested_source/Nested"
printf nested > "$nested_source/Nested/file.wav"
assert_failure "nested source directory rejected" run_revision --source "$nested_source"

symlink_source="$tmp/symlink-source"
mkdir "$symlink_source"
ln -s "$source_dir/Blue Sky Main.wav" "$symlink_source/linked.wav"
assert_failure "source symlink rejected" run_revision --source "$symlink_source"

reserved_source="$tmp/reserved-source"
mkdir "$reserved_source"
printf notes > "$reserved_source/Revision_Notes.md"
assert_failure "reserved notes source rejected" run_revision --source "$reserved_source"

# Unexpected canonical revision paths invalidate state rather than being adopted.
mkdir "$project_root/04_Revisions/Revision_04"
assert_failure "unrecorded revision directory rejected" run_revision
rmdir "$project_root/04_Revisions/Revision_04"

# Injected failure after the coordinated directory commit restores both the
# prior manifest and the absence of the proposed revision directory.
manifest_before="$tmp/manifest-before.json"
cp "$manifest" "$manifest_before"
assert_failure "coordinated commit failure rolls back revision" \
    env JL_MIXING_FAIL_AT=after-coordinated-directory \
        JL_MIXING_HOME="$ROOT" JL_MIXING_ROOT="$studio_root" \
        "$ROOT/bin/new-revision" --project "$project_root" --description 'Rollback revision'
assert_same_bytes "$manifest_before" "$manifest"
assert_path_not_exists "$project_root/04_Revisions/Revision_04"

# A project created by v1.2 new-mix already owns Revision 1, so the unchanged
# new-revision command must create Revision 2 without migration or special cases.
JL_MIXING_ROOT="$studio_root" "$ROOT/bin/new-mix" --client acme \
    'Created with Revision One' --no-cd >/dev/null
v12_project="$studio_root/Clients/Acme Records/Projects/Created with Revision One"
v12_manifest="$v12_project/00_Admin/project-manifest.json"
assert_file_exists "$v12_project/04_Revisions/Revision_01/Revision_Notes.md"
"$ROOT/bin/new-revision" --project "$v12_project" --no-cd >/dev/null
assert_file_exists "$v12_project/04_Revisions/Revision_02/Revision_Notes.md"
assert_json_eq '2' "$v12_manifest" '.state.current_revision' \
    "new-revision advances a v1.2-created project to Revision 2"
assert_json_eq 'Revision 2' "$v12_manifest" '.revisions[1].description' \
    "v1.2-created project keeps the existing later-revision default"

echo "[OK] new-revision ($TEST_COUNT assertions)"
