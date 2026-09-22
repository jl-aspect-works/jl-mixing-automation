#!/usr/bin/env bash
set -eu

# Purpose: Verify the v1.1 command contract while preserving v1.0.4 intake QC.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/integration/integration-helper.sh"

make_fake_ffprobe() {
    local bin_dir
    bin_dir="$1"
    mkdir -p "$bin_dir"
    cat > "$bin_dir/ffprobe" <<'FFPROBE'
#!/usr/bin/env bash
set -eu
path=""
for argument in "$@"; do path="$argument"; done
case "$path" in
    *Bad.wav)
        printf 'invalid data found when processing input\n' >&2
        exit 1
        ;;
    *Lead\ Vocal.wav)
        printf '%s\n' '{"streams":[{"sample_rate":"44100","bits_per_raw_sample":"16","channels":2}],"format":{"duration":"123.45"}}'
        ;;
    *)
        printf '%s\n' '{"streams":[{"sample_rate":"48000","bits_per_raw_sample":"24","channels":2}],"format":{"duration":"2.00"}}'
        ;;
esac
FFPROBE
    chmod +x "$bin_dir/ffprobe"
}

run_capture() {
    local output_file status_file
    output_file="$1"
    status_file="$2"
    shift 2
    set +e
    "$@" >"$output_file" 2>&1
    printf '%s\n' "$?" >"$status_file"
    set -e
}

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
fake_bin="$tmp/fake-bin"
make_fake_ffprobe "$fake_bin"

# Arrange a canonical v1.1 project with every preserved finding category.
studio_root="$tmp/studio"
project_root="$(fixture_v11_project "$studio_root")"
report="$project_root/00_Admin/Intake_Report.md"
source_root="$project_root/01_Client_Files/Original_Delivery"
mkdir -p "$source_root/Audio" "$source_root/Drums" "$source_root/Samples" "$source_root/Documentation"
printf 'lead\n' > "$source_root/Audio/Lead Vocal.wav"
printf 'kick one\n' > "$source_root/Drums/Kick.wav"
printf 'kick two\n' > "$source_root/Samples/Kick.wav"
printf 'notes\n' > "$source_root/Documentation/Track Notes.pdf"
ln -s "$source_root/Audio/Lead Vocal.wav" "$source_root/Audio/Linked Vocal.wav"

python3 - "$report" <<'PY_REPORT'
from pathlib import Path
import sys
path = Path(sys.argv[1])
path.write_bytes(
    b"# Intake Report\n\nEngineer prefix: preserve exactly.\n\n"
    b"<!-- BEGIN AUTOMATED SECTION -->\nold managed content\n"
    b"<!-- END AUTOMATED SECTION -->\n\nEngineer suffix: preserve exactly.\n"
)
PY_REPORT
python3 - "$report" "$tmp/outside-before.bin" <<'PY_OUTSIDE'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_bytes()
begin = b"<!-- BEGIN AUTOMATED SECTION -->"
end = b"<!-- END AUTOMATED SECTION -->"
outside = text[: text.index(begin) + len(begin)] + text[text.index(end):]
Path(sys.argv[2]).write_bytes(outside)
PY_OUTSIDE

output="$tmp/validate.out"
status="$tmp/validate.status"
run_capture "$output" "$status" env PATH="$fake_bin:$PATH" \
    "$ROOT/bin/validate-intake" --project "$project_root"
assert_eq "0" "$(cat "$status")" "warnings do not block intake validation"
report_text="$(cat "$report")"
command_text="$(cat "$output")"
assert_contains "$report_text" "## Intake Summary" "summary section is generated"
assert_contains "$report_text" "## Critical Errors" "critical-error section is generated"
assert_contains "$report_text" "## Duplicate Filenames" "duplicate section is generated"
assert_contains "$report_text" '`Drums/Kick.wav`, `Samples/Kick.wav`' "duplicate basenames are reported"
assert_contains "$report_text" "## Project-Format Mismatches" "format-mismatch section is generated"
assert_contains "$report_text" '`Audio/Lead Vocal.wav`: 44100 Hz; expected 48000 Hz.' "sample-rate mismatch is preserved"
assert_contains "$report_text" '`Audio/Lead Vocal.wav`: 16-bit; expected 24-bit.' "bit-depth mismatch is preserved"
assert_contains "$report_text" "## Unsupported or Non-Audio Files" "unsupported section is generated"
assert_contains "$report_text" '`Documentation/Track Notes.pdf`' "unsupported file is reported"
assert_contains "$report_text" "Files discovered: 4" "symlink files are not followed"
assert_contains "$report_text" "Warnings: 4" "warning count preserves v1.0.4 severities"
assert_contains "$report_text" "48000 Hz, 24-bit, 2 ch, 2.00 s" "technical metadata remains in inventory"
assert_contains "$command_text" "Intake validation completed." "success summary is printed"
assert_contains "$command_text" "Review 00_Admin/Intake_Report.md" "success next step is printed"
assert_contains "$command_text" "Prepare accepted audio in 02_Audio_Preparation/Working_Audio/" "preparation guidance is printed"

python3 - "$report" "$tmp/outside-after.bin" <<'PY_OUTSIDE'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_bytes()
begin = b"<!-- BEGIN AUTOMATED SECTION -->"
end = b"<!-- END AUTOMATED SECTION -->"
outside = text[: text.index(begin) + len(begin)] + text[text.index(end):]
Path(sys.argv[2]).write_bytes(outside)
PY_OUTSIDE
assert_same_bytes "$tmp/outside-before.bin" "$tmp/outside-after.bin"

# Dry-run prints the proposed section, honors overrides/skips, and changes no file.
override_source="$tmp/override-source"
mkdir -p "$override_source"
printf 'lead\n' > "$override_source/Lead Vocal.wav"
cp "$report" "$tmp/report-before-dry-run.md"
run_capture "$output" "$status" env PATH="$fake_bin:$PATH" \
    "$ROOT/bin/validate-intake" --project "$project_root" --source "$override_source" --dry-run \
    --no-duplicate-check --expected-sample-rate 44100 --expected-bit-depth 16
assert_eq "0" "$(cat "$status")" "dry-run returns preserved validation status"
dry_text="$(cat "$output")"
assert_contains "$dry_text" "Duplicate-basename detection was skipped." "skipped duplicate check is explicit"
assert_contains "$dry_text" "## Project-Format Mismatches" "dry-run prints managed report content"
assert_contains "$dry_text" "## Project-Format Mismatches

- None." "matching overrides remove format mismatches"
assert_same_bytes "$report" "$tmp/report-before-dry-run.md"

# Known removed options receive targeted migration diagnostics.
run_capture "$output" "$status" "$ROOT/bin/validate-intake" --report-only
assert_eq "2" "$(cat "$status")" "removed report-only option is an argument error"
assert_contains "$(cat "$output")" "--report-only was removed in JL Mixing 1.1." "report-only diagnostic is targeted"
run_capture "$output" "$status" "$ROOT/bin/validate-intake" --non-interactive
assert_eq "2" "$(cat "$status")" "removed non-interactive option is an argument error"
assert_contains "$(cat "$output")" "--non-interactive was removed in JL Mixing 1.1." "non-interactive diagnostic is targeted"

printf '[OK] validate-intake (%s assertions)\n' "$TEST_COUNT"
