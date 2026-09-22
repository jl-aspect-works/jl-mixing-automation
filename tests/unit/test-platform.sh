#!/usr/bin/env bash
set -eu

# Purpose: Verify portable path, stat, checksum, and temporary-file behavior.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
. "$ROOT/lib/platform.sh"

# Arrange: build an isolated temporary fixture.
tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT
printf 'abc' > "$tmp/file"

platform="$(jl_platform_name)"
case "$platform" in macos|linux) pass "supported platform detected" ;; *) fail "unsupported platform: $platform" ;; esac
# Assert: verify observable behavior rather than internal implementation.
assert_eq "3" "$(jl_stat_size "$tmp/file")" "portable file size"
assert_eq "$(cd "$tmp" && pwd)/file" "$(jl_realpath "$tmp/file")" "portable realpath"
hash="$(jl_sha256 "$tmp/file")"
assert_eq "64" "${#hash}" "SHA-256 length"
made="$(jl_mktemp_dir jl-platform-test)"
assert_dir_exists "$made"
rm -rf "$made"
echo "[OK] platform.sh ($TEST_COUNT assertions)"
