#!/usr/bin/env bash
set -eu

# Purpose: Verify no-follow source planning and copy behavior independently of
# the slower command-level schema workflow.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=tests/test-helper.sh
. "$ROOT/tests/test-helper.sh"

require_test_command python3

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
source_root="$tmp/source"
destination="$tmp/destination"
plan="$tmp/plan.json"
mkdir -p "$source_root/Audio/Drums" "$source_root/Docs/Empty" "$destination"
printf 'kick\n' > "$source_root/Audio/Drums/Kick.wav"
printf 'notes\n' > "$source_root/Docs/notes.txt"

python3 "$ROOT/tools/import-project-source.py" scan "$source_root" "$plan"
assert_file_exists "$plan"
assert_eq 'directory' "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_type"])' "$plan")" \
    "directory source type"
assert_contains "$(cat "$plan")" 'Audio/Drums/Kick.wav' "nested file planned"
assert_contains "$(cat "$plan")" 'Docs/Empty' "empty directory planned"

python3 "$ROOT/tools/import-project-source.py" copy "$source_root" "$destination" "$plan"
assert_file_exists "$destination/Audio/Drums/Kick.wav"
assert_file_exists "$destination/Docs/notes.txt"
assert_dir_exists "$destination/Docs/Empty"
assert_same_bytes "$source_root/Audio/Drums/Kick.wav" "$destination/Audio/Drums/Kick.wav"

# A changed source tree cannot be copied using a stale plan.
mkdir -p "$tmp/changed-destination"
printf 'later\n' > "$source_root/later.txt"
assert_failure "changed source rejected" \
    python3 "$ROOT/tools/import-project-source.py" copy \
        "$source_root" "$tmp/changed-destination" "$plan"
rm "$source_root/later.txt"

# Neither a source symlink nor a nested source symlink may be followed.
ln -s "$source_root" "$tmp/source-link"
assert_failure "source symlink rejected" \
    python3 "$ROOT/tools/import-project-source.py" scan "$tmp/source-link" "$tmp/link-plan.json"
ln -s "$source_root/Audio/Drums/Kick.wav" "$source_root/linked.wav"
assert_failure "nested symlink rejected" \
    python3 "$ROOT/tools/import-project-source.py" scan "$source_root" "$tmp/nested-link-plan.json"
rm "$source_root/linked.wav"

# Case-collision coverage is conditional because a case-insensitive filesystem
# cannot create the fixture in the first place.
case_source="$tmp/case-source"
mkdir -p "$case_source"
printf A > "$case_source/Print.wav"
printf B > "$case_source/print.wav" 2>/dev/null || true
if [ -f "$case_source/Print.wav" ] && [ -f "$case_source/print.wav" ] && \
   [ "$(cat "$case_source/Print.wav")" != "$(cat "$case_source/print.wav")" ]; then
    assert_failure "case-insensitive source collision rejected" \
        python3 "$ROOT/tools/import-project-source.py" scan \
            "$case_source" "$tmp/case-plan.json"
else
    pass "case-collision fixture unavailable on this filesystem"
fi

# One regular-file source is copied directly by basename.
file_source="$tmp/Single Mix.wav"
printf 'mix\n' > "$file_source"
file_plan="$tmp/file-plan.json"
file_destination="$tmp/file-destination"
mkdir -p "$file_destination"
python3 "$ROOT/tools/import-project-source.py" scan "$file_source" "$file_plan"
python3 "$ROOT/tools/import-project-source.py" copy "$file_source" "$file_destination" "$file_plan"
assert_file_exists "$file_destination/Single Mix.wav"
assert_same_bytes "$file_source" "$file_destination/Single Mix.wav"

printf '[OK] import-project-source (%s assertions)\n' "$TEST_COUNT"
