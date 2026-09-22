#!/usr/bin/env bash
set -eu

# Purpose: Verify safe creation, exact copy, atomic write, move, and immutability guards.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
. "$ROOT/lib/filesystem.sh"

# Arrange: build an isolated temporary fixture.
tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT

jl_fs_ensure_directory "$tmp/a/b"
# Assert: verify observable behavior rather than internal implementation.
assert_dir_exists "$tmp/a/b"
printf 'original' > "$tmp/source.txt"
jl_fs_copy_file_exact "$tmp/source.txt" "$tmp/copy.txt"
assert_file_exists "$tmp/copy.txt"
assert_success "exact copy bytes match" jl_fs_same_bytes "$tmp/source.txt" "$tmp/copy.txt"
assert_failure "copy refuses overwrite" jl_fs_copy_file_exact "$tmp/source.txt" "$tmp/copy.txt"
printf 'atomic' | jl_fs_atomic_write "$tmp/atomic.txt"
assert_eq "atomic" "$(cat "$tmp/atomic.txt")" "atomic write content"
immutable="$tmp/Project/01_Client_Files/Original_Delivery/file.wav"
assert_failure "immutable destination is rejected" jl_fs_assert_mutable_path "$immutable"
printf 'move' > "$tmp/move.txt"
jl_fs_safe_move "$tmp/move.txt" "$tmp/moved/file.txt"
assert_file_exists "$tmp/moved/file.txt"
mkdir "$tmp/empty"
assert_success "empty directory detected" jl_fs_directory_is_empty "$tmp/empty"
assert_success "safe absolute path accepted" jl_path_validate_absolute "$tmp/root/path"
assert_failure "relative absolute path rejected" jl_path_validate_absolute 'root/path'
assert_failure "absolute dot segment rejected" jl_path_validate_absolute "$tmp/root/../path"
assert_success "safe relative path accepted" jl_path_validate_relative 'Stems/Drums.wav'
assert_failure "absolute relative path rejected" jl_path_validate_relative '/Stems/Drums.wav'
assert_failure "dot-dot path rejected" jl_path_validate_relative '../Drums.wav'
assert_failure "empty relative segment rejected" jl_path_validate_relative 'Stems//Drums.wav'
assert_failure "backslash relative path rejected" jl_path_validate_relative 'Stems\\Drums.wav'
assert_eq "$tmp/root/Stems/Drums.wav" \
    "$(mkdir -p "$tmp/root"; jl_path_resolve_under_root "$tmp/root" 'Stems/Drums.wav')" \
    "relative path resolved beneath root"

mkdir -p "$tmp/collision"
touch "$tmp/collision/Blue Sky.wav"
assert_failure "case-insensitive child collision rejected" \
    jl_fs_assert_no_case_insensitive_child_collision "$tmp/collision" 'blue sky.WAV'
assert_success "distinct child name accepted" \
    jl_fs_assert_no_case_insensitive_child_collision "$tmp/collision" 'Instrumental.wav'

mkdir -p "$tmp/safe-root/real/sub"
ln -s "$tmp/safe-root/real" "$tmp/safe-root/link"
assert_success "real path components accepted" \
    jl_fs_assert_no_symlink_components "$tmp/safe-root" "$tmp/safe-root/real/sub/file.wav"
assert_failure "symlink path component rejected" \
    jl_fs_assert_no_symlink_components "$tmp/safe-root" "$tmp/safe-root/link/file.wav"
ln -s "$tmp/safe-root" "$tmp/safe-root-alias"
assert_failure "symlink root rejected" \
    jl_fs_assert_no_symlink_components "$tmp/safe-root-alias" "$tmp/safe-root-alias/real/file.wav"
assert_success "same filesystem detected" jl_fs_same_filesystem "$tmp" "$tmp/missing/path"

mkdir -p "$tmp/Project/03_DAW_Project"
assert_failure "opaque DAW content is not automation-owned" \
    jl_fs_assert_automation_owned_path "$tmp/Project/03_DAW_Project/session.logicx"

mkdir -p "$tmp/remove-dir"
printf 'x' > "$tmp/remove-dir/file"
ln -s "$tmp/remove-dir" "$tmp/remove-link"
jl_fs_remove_entry_no_follow "$tmp/remove-link"
assert_path_not_exists "$tmp/remove-link"
assert_dir_exists "$tmp/remove-dir"
echo "[OK] filesystem.sh ($TEST_COUNT assertions)"
