#!/usr/bin/env bash
set -eu

# Purpose: Verify same-filesystem staging, coordinated commit, and rollback hooks.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
. "$ROOT/lib/transaction.sh"

# Arrange: build an isolated temporary fixture.
tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/project/00_Admin"

stage="$(jl_txn_stage_directory_near "$tmp/project/NewDirectory")"
printf 'new' > "$stage/file.txt"
jl_txn_commit_new_directory "$stage" "$tmp/project/NewDirectory"
assert_eq "new" "$(cat "$tmp/project/NewDirectory/file.txt")" "new directory committed"

stage="$(jl_txn_stage_directory_near "$tmp/project/FailedNewDirectory")"
printf 'temporary' > "$stage/file.txt"
assert_failure "post-commit failure removes newly created directory" \
    env JL_MIXING_FAIL_AT=after-directory-commit bash -c \
    '. "$1/lib/transaction.sh"; jl_txn_commit_new_directory "$2" "$3"' \
    _ "$ROOT" "$stage" "$tmp/project/FailedNewDirectory"
assert_path_not_exists "$tmp/project/FailedNewDirectory"

mkdir -p "$tmp/project/ReplaceMe"
printf 'old' > "$tmp/project/ReplaceMe/value.txt"
stage="$(jl_txn_stage_directory_near "$tmp/project/ReplaceMe")"
printf 'new' > "$stage/value.txt"
jl_txn_replace_directory "$stage" "$tmp/project/ReplaceMe"
assert_eq "new" "$(cat "$tmp/project/ReplaceMe/value.txt")" "directory replacement committed"

printf 'old-again' > "$tmp/project/ReplaceMe/value.txt"
stage="$(jl_txn_stage_directory_near "$tmp/project/ReplaceMe")"
printf 'should-rollback' > "$stage/value.txt"
assert_failure "injected directory failure returns error" \
    env JL_MIXING_FAIL_AT=after-directory-replacement bash -c \
    '. "$1/lib/transaction.sh"; jl_txn_replace_directory "$2" "$3"' \
    _ "$ROOT" "$stage" "$tmp/project/ReplaceMe"
assert_eq "old-again" "$(cat "$tmp/project/ReplaceMe/value.txt")" "directory rollback restored prior content"

mkdir -p "$tmp/project/05_Final_Delivery"
printf 'old delivery' > "$tmp/project/05_Final_Delivery/old.txt"
printf '{"old":true}\n' > "$tmp/project/00_Admin/project-manifest.json"
stage_dir="$(jl_txn_stage_directory_near "$tmp/project/05_Final_Delivery")"
printf 'new delivery' > "$stage_dir/new.txt"
stage_file="$(jl_mktemp_file_near "$tmp/project/00_Admin/project-manifest.json")"
printf '{"new":true}\n' > "$stage_file"
jl_txn_commit_directory_and_file \
    "$stage_dir" "$tmp/project/05_Final_Delivery" \
    "$stage_file" "$tmp/project/00_Admin/project-manifest.json"
assert_file_exists "$tmp/project/05_Final_Delivery/new.txt"
assert_contains "$(cat "$tmp/project/00_Admin/project-manifest.json")" '"new":true' \
    "coordinated manifest committed"

# Arrange a second replacement and inject failure after the directory commit.
printf 'stable delivery' > "$tmp/project/05_Final_Delivery/stable.txt"
printf '{"stable":true}\n' > "$tmp/project/00_Admin/project-manifest.json"
stage_dir="$(jl_txn_stage_directory_near "$tmp/project/05_Final_Delivery")"
printf 'bad delivery' > "$stage_dir/bad.txt"
stage_file="$(jl_mktemp_file_near "$tmp/project/00_Admin/project-manifest.json")"
printf '{"bad":true}\n' > "$stage_file"
assert_failure "coordinated failure returns error" \
    env JL_MIXING_FAIL_AT=after-coordinated-directory bash -c \
    '. "$1/lib/transaction.sh"; jl_txn_commit_directory_and_file "$2" "$3" "$4" "$5"' \
    _ "$ROOT" "$stage_dir" "$tmp/project/05_Final_Delivery" \
    "$stage_file" "$tmp/project/00_Admin/project-manifest.json"
assert_file_exists "$tmp/project/05_Final_Delivery/stable.txt"
assert_contains "$(cat "$tmp/project/00_Admin/project-manifest.json")" '"stable":true' \
    "coordinated rollback restored manifest"


# Optional committed-state verification runs before backups are discarded.
printf 'verified-old delivery' > "$tmp/project/05_Final_Delivery/value.txt"
printf '{"verified_old":true}
' > "$tmp/project/00_Admin/project-manifest.json"
stage_dir="$(jl_txn_stage_directory_near "$tmp/project/05_Final_Delivery")"
printf 'verified-new delivery' > "$stage_dir/value.txt"
stage_file="$(jl_mktemp_file_near "$tmp/project/00_Admin/project-manifest.json")"
printf '{"verified_new":true}
' > "$stage_file"
assert_failure "coordinated verifier failure rolls back both targets"     jl_txn_commit_directory_and_file         "$stage_dir" "$tmp/project/05_Final_Delivery"         "$stage_file" "$tmp/project/00_Admin/project-manifest.json" false
assert_eq "verified-old delivery"     "$(cat "$tmp/project/05_Final_Delivery/value.txt")"     "verifier rollback restored directory"
assert_contains "$(cat "$tmp/project/00_Admin/project-manifest.json")"     '"verified_old":true' "verifier rollback restored file"

# File-only replacement supports the same rollback-capable verification flow.
printf 'old file
' > "$tmp/project/00_Admin/file-only.json"
stage_file="$(jl_mktemp_file_near "$tmp/project/00_Admin/file-only.json")"
printf 'new file
' > "$stage_file"
jl_txn_replace_file "$stage_file" "$tmp/project/00_Admin/file-only.json" true
assert_eq "new file" "$(cat "$tmp/project/00_Admin/file-only.json")"     "file-only transaction committed"

printf 'stable file
' > "$tmp/project/00_Admin/file-only.json"
stage_file="$(jl_mktemp_file_near "$tmp/project/00_Admin/file-only.json")"
printf 'bad file
' > "$stage_file"
assert_failure "file verifier failure rolls back replacement"     jl_txn_replace_file "$stage_file" "$tmp/project/00_Admin/file-only.json" false
assert_eq "stable file" "$(cat "$tmp/project/00_Admin/file-only.json")"     "file-only rollback restored prior content"

echo "[OK] transaction.sh ($TEST_COUNT assertions)"
