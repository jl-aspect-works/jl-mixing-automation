#!/usr/bin/env bash
# Build and verify the same release archive an end user will download.
set -eu

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"

require_test_command python3
require_test_command jq
python3 -c 'import jsonschema' >/dev/null 2>&1 || {
    if [ "${JL_TEST_STRICT:-0}" = "1" ]; then
        fail "Release tests require the jsonschema package."
    fi
    echo "[SKIP] Release tests require jsonschema."
    exit 0
}

temp_root="$(new_test_dir)"
trap 'rm -rf "$temp_root"' EXIT HUP INT TERM
"$ROOT/tools/build-release" --output-dir "$temp_root/dist" --platform test >/dev/null
archive="$(find "$temp_root/dist" -name '*.tar.gz' -type f | head -n 1)"
[ -n "$archive" ] || fail "release archive was not created"
pass "release archive created"
assert_file_exists "$archive.sha256"
assert_file_exists "$archive.inventory.txt"
assert_contains "$(cat "$archive.inventory.txt")" 'API_VERSION' \
    "Automation API version included in release archive"
assert_contains "$(cat "$archive.inventory.txt")" 'bin/jl-mixing' \
    "Automation API dispatcher included in release archive"
assert_contains "$(cat "$archive.inventory.txt")" 'src/jl_mixing/__init__.py' \
    "Python runtime included in release archive"
assert_contains "$(cat "$archive.inventory.txt")" 'api/schemas/v1.0/system-info.schema.json' \
    "Automation API schema included in release archive"
assert_contains "$(cat "$archive.inventory.txt")" 'api/examples/v1.0/success/system-info.json' \
    "Automation API example included in release archive"
assert_contains "$(cat "$archive.inventory.txt")" 'tools/project-state.py' \
    "project-state tool included in release archive"
assert_contains "$(cat "$archive.inventory.txt")" 'schemas/client-profile-snapshot.schema.json' \
    "snapshot schema included in release archive"
assert_contains "$(cat "$archive.inventory.txt")" 'templates/Intake_Report.md' \
    "canonical Markdown templates included in release archive"
assert_contains "$(cat "$archive.inventory.txt")" 'bin/jl-mixing-shell-integration' \
    "shell integration included in release archive"
assert_contains "$(cat "$archive.inventory.txt")" 'tools/manage-shell-config.py' \
    "shell configuration helper included in release archive"
assert_contains "$(cat "$archive.inventory.txt")" 'CHANGELOG.md' \
    "changelog included in release archive"
assert_contains "$(cat "$archive.inventory.txt")" 'docs/RELEASE_NOTES_V1.2.md' \
    "v1.2 release notes included in release archive"
assert_contains "$(cat "$archive.inventory.txt")" 'docs/RELEASE_NOTES_V1.3.md' \
    "v1.3 release notes included in release archive"
assert_failure "obsolete complete-project omitted from release archive" \
    grep -q 'bin/complete-project' "$archive.inventory.txt"
verify_output="$(
    "$ROOT/tools/verify-release-archive" "$archive" 2>&1
)" || {
    printf '%s\n' "$verify_output" >&2
    fail "release archive verifies"
}

printf '%s\n' "$verify_output"
pass "release archive verifies"
echo "[OK] release package ($TEST_COUNT assertions)"
