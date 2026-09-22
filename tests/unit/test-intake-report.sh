#!/usr/bin/env bash
set -eu

# Purpose: Exercise the report helper when optional ffprobe is unavailable.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"

require_test_command python3

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
source_root="$tmp/source"
mkdir -p "$source_root/A" "$source_root/B" "$tmp/empty-path"
printf 'one\n' > "$source_root/A/Same.wav"
printf 'two\n' > "$source_root/B/Same.wav"
printf 'notes\n' > "$source_root/Notes.txt"

output="$tmp/report.md"
summary="$tmp/summary.json"
PATH="$tmp/empty-path" "$(command -v python3)" "$ROOT/tools/build-intake-report.py" \
    --source "$source_root" --output "$output" --summary-output "$summary" \
    --expected-sample-rate 48000 --expected-bit-depth 24

text="$(cat "$output")"
assert_contains "$text" "ffprobe is not installed; enhanced audio inspection was unavailable." "unavailable ffprobe is explicit"
assert_contains "$text" "Warnings: 3" "unavailable ffprobe retains warning semantics"
assert_contains "$text" '`A/Same.wav`, `B/Same.wav`' "duplicate basename is reported without ffprobe"
assert_contains "$text" '`Notes.txt`' "unsupported file is reported without ffprobe"
assert_json_eq "3" "$summary" '.files_discovered' "summary records file count"
assert_json_eq "0" "$summary" '.blocking_errors' "summary records no blocking errors"
assert_json_eq "3" "$summary" '.warnings' "summary records warning count"
assert_json_eq "false" "$summary" '(.ffprobe_available | tostring)' "summary records unavailable ffprobe"


# Empty sources preserve the v1.0.4 blocking result and inventory presentation.
empty_source="$tmp/empty-source"
mkdir -p "$empty_source"
set +e
PATH="$tmp/empty-path" "$(command -v python3)" "$ROOT/tools/build-intake-report.py" \
    --source "$empty_source" --output "$tmp/empty-report.md" \
    --summary-output "$tmp/empty-summary.json" --expected-sample-rate 48000 \
    --expected-bit-depth 24
empty_status=$?
set -e
assert_eq "5" "$empty_status" "empty source remains blocking"
assert_contains "$(cat "$tmp/empty-report.md")" "No files were found in the intake source." "empty-source error is reported"
assert_contains "$(cat "$tmp/empty-report.md")" "| _No files_ | 0 | — |" "empty inventory row is reported"

printf '[OK] intake report helper (%s assertions)\n' "$TEST_COUNT"
