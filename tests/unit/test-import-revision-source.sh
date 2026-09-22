#!/usr/bin/env bash
set -eu

# Purpose: Verify safe immediate-file planning and copying for new-revision.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
require_test_command python3

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
tool="$ROOT/tools/import-revision-source.py"
source_dir="$tmp/source"
destination="$tmp/destination"
plan="$tmp/plan.json"
mkdir -p "$source_dir" "$destination"
printf 'main\n' > "$source_dir/Blue Sky Main.wav"
printf 'instrumental\n' > "$source_dir/Blue Sky Instrumental.wav"

python3 "$tool" scan "$source_dir" "$plan"
assert_eq '["Blue Sky Instrumental.wav","Blue Sky Main.wav"]' \
    "$(jq -c '.files' "$plan")" "deterministic immediate-file plan"
python3 "$tool" copy "$source_dir" "$destination" "$plan"
assert_file_exists "$destination/Blue Sky Main.wav"
assert_file_exists "$destination/Blue Sky Instrumental.wav"
assert_same_bytes "$source_dir/Blue Sky Main.wav" "$destination/Blue Sky Main.wav"

single_plan="$tmp/single.json"
single_destination="$tmp/single-destination"
mkdir "$single_destination"
python3 "$tool" scan "$source_dir/Blue Sky Main.wav" "$single_plan"
python3 "$tool" copy "$source_dir/Blue Sky Main.wav" "$single_destination" "$single_plan"
assert_file_exists "$single_destination/Blue Sky Main.wav"

mkdir "$source_dir/Nested"
assert_failure "nested source directories rejected" python3 "$tool" scan "$source_dir" "$plan"
rmdir "$source_dir/Nested"
ln -s "$source_dir/Blue Sky Main.wav" "$source_dir/link.wav"
assert_failure "source symlinks rejected" python3 "$tool" scan "$source_dir" "$plan"
rm "$source_dir/link.wav"
printf 'reserved\n' > "$source_dir/Revision_Notes.md"
assert_failure "reserved notes filename rejected" python3 "$tool" scan "$source_dir" "$plan"
rm "$source_dir/Revision_Notes.md"

case_dir="$tmp/case-source"
mkdir "$case_dir"
printf A > "$case_dir/Print.wav"
printf B > "$case_dir/print.wav" 2>/dev/null || true
if [ -f "$case_dir/Print.wav" ] && [ -f "$case_dir/print.wav" ] && \
   [ "$(cat "$case_dir/Print.wav")" != "$(cat "$case_dir/print.wav")" ]; then
    assert_failure "case-insensitive file collisions rejected" \
        python3 "$tool" scan "$case_dir" "$tmp/case-plan.json"
else
    pass "case-insensitive fixture unavailable on this filesystem"
fi

# A changed source plan is rejected before any copy occurs.
change_source="$tmp/change-source"
change_destination="$tmp/change-destination"
mkdir "$change_source" "$change_destination"
printf first > "$change_source/First.wav"
python3 "$tool" scan "$change_source" "$tmp/change-plan.json"
printf second > "$change_source/Second.wav"
assert_failure "changed source rejected during copy" \
    python3 "$tool" copy "$change_source" "$change_destination" "$tmp/change-plan.json"
if find "$change_destination" -mindepth 1 -print -quit | grep -q .; then
    fail "changed-source copy left destination content"
fi
pass "changed-source copy leaves destination empty"

echo "[OK] import-revision-source.py ($TEST_COUNT assertions)"
