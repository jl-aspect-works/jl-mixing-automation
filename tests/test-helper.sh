#!/usr/bin/env bash
# Lightweight assertion and temporary-workspace helpers for shell tests.
#
# The suite intentionally avoids a third-party test framework so it runs on the
# same Bash 3.2 baseline as the application.
set -eu

# Shared by tests that source this helper.
# shellcheck disable=SC2034
TEST_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_COUNT=0

# Terminate the current test with a formatted failure message.
fail() {
    echo "[FAIL] $*" >&2
    exit 1
}

# Count and report one successful assertion.
pass() {
    TEST_COUNT=$((TEST_COUNT + 1))
    echo "[PASS] $*"
}

# Compare two strings and report the supplied assertion label.
assert_eq() {
    expected="$1"
    actual="$2"
    message="$3"
    [ "$expected" = "$actual" ] || fail "$message: expected '$expected', got '$actual'"
    pass "$message"
}

# Assert that a regular file exists.
assert_file_exists() {
    [ -f "$1" ] || fail "Expected file: $1"
    pass "file exists: $1"
}

# Assert that a directory exists.
assert_dir_exists() {
    [ -d "$1" ] || fail "Expected directory: $1"
    pass "directory exists: $1"
}

# Assert that one string contains another literal string.
assert_contains() {
    haystack="$1"
    needle="$2"
    message="$3"
    case "$haystack" in
        *"$needle"*) pass "$message" ;;
        *) fail "$message: '$needle' not found" ;;
    esac
}

# Assert that a command returns zero while suppressing its output.
assert_success() {
    message="$1"
    shift
    "$@" >/dev/null 2>&1 || fail "$message"
    pass "$message"
}

# Assert that a command returns nonzero while suppressing its output.
assert_failure() {
    message="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        fail "$message"
    fi
    pass "$message"
}

# Skip optional tests or fail strict mode when a dependency is missing.
require_test_command() {
    command_name="$1"
    if command -v "$command_name" >/dev/null 2>&1; then
        return 0
    fi
    if [ "${JL_TEST_STRICT:-0}" = "1" ]; then
        fail "Required strict-test command is missing: $command_name"
    fi
    echo "[SKIP] $command_name-dependent tests: command is not installed."
    exit 0
}

# Create and canonicalize a temporary directory, avoiding macOS /var aliases.
new_test_dir() {
    local temp_dir
    temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/jl-mixing-test.XXXXXX")" || return $?
    (cd "$temp_dir" && pwd -P)
}

# Assert that no filesystem entry exists at a path.
assert_path_not_exists() {
    [ ! -e "$1" ] || fail "Expected path not to exist: $1"
    pass "path does not exist: $1"
}

# Evaluate a jq filter and compare the scalar result.
assert_json_eq() {
    local expected file filter actual message
    expected="$1"
    file="$2"
    filter="$3"
    message="$4"
    actual="$(jq -er "$filter" "$file")" || fail "$message: jq filter failed"
    assert_eq "$expected" "$actual" "$message"
}

# Assert that two files are byte-for-byte identical.
assert_same_bytes() {
    cmp -s "$1" "$2" || fail "Files differ: $1 and $2"
    pass "files have identical bytes"
}
