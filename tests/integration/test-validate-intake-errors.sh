#!/usr/bin/env bash
set -eu

# Purpose: Verify blocking intake findings still update the managed report.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/integration/integration-helper.sh"

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
fake_bin="$tmp/fake-bin"
mkdir -p "$fake_bin"
cat > "$fake_bin/ffprobe" <<'FFPROBE'
#!/usr/bin/env bash
printf 'invalid data found when processing input\n' >&2
exit 1
FFPROBE
chmod +x "$fake_bin/ffprobe"

project_root="$(fixture_v11_project "$tmp/studio")"
report="$project_root/00_Admin/Intake_Report.md"
printf 'bad\n' > "$project_root/01_Client_Files/Original_Delivery/Bad.wav"

set +e
PATH="$fake_bin:$PATH" "$ROOT/bin/validate-intake" --project "$project_root" \
    >"$tmp/output" 2>&1
status=$?
set -e
assert_eq "5" "$status" "unreadable candidate audio remains blocking"
report_text="$(cat "$report")"
command_text="$(cat "$tmp/output")"
assert_contains "$report_text" 'Unreadable audio file `Bad.wav`' "blocking error is written to report"
assert_contains "$report_text" "not readable" "unreadable inventory status is clear"
assert_contains "$command_text" "completed with blocking errors" "blocking summary is truthful"
assert_contains "$command_text" "Review and resolve the critical errors" "blocking next step is printed"

printf '[OK] validate-intake blocking findings (%s assertions)\n' "$TEST_COUNT"
