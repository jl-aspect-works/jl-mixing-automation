#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/integration/integration-helper.sh"
expected_created_with="jl-mixing $(cat "$ROOT/VERSION")"
# Use a portable non-UTC POSIX timezone so the filename test proves that the
# archive uses local wall-clock time rather than the UTC manifest timestamp.
TZ=EST5EDT
export TZ
require_test_command jq
require_test_command python3
if ! command -v zip >/dev/null 2>&1; then
    if [ "${JL_TEST_STRICT:-0}" = 1 ]; then fail 'zip is required for strict delivery ZIP tests'; fi
    echo '[SKIP] zip is not installed.'
    exit 0
fi
python3 -c 'import jsonschema' >/dev/null 2>&1 || { echo '[SKIP] create-delivery ZIP requires jsonschema.'; exit 0; }

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
studio_root="$tmp/studio"
project_root="$(fixture_v11_approved_project "$studio_root")"
revision="$project_root/04_Revisions/Revision_01"
delivery="$project_root/05_Final_Delivery"
dm="$delivery/delivery-manifest.json"
project_manifest="$project_root/00_Admin/project-manifest.json"
printf 'main\n' > "$revision/Blue Sky Main Mix.wav"
printf 'user attachment\n' > "$delivery/client-reference.pdf"

# Follow the documented two-step workflow: create the editable delivery first,
# edit Delivery_Notes.md, then rebuild the same package with ZIP output.
(cd "$project_root" && "$ROOT/bin/create-delivery" >/dev/null)
printf '\nFinal client notes\n' >> "$delivery/Delivery_Notes.md"
expected_local_hour="$(date '+%Y%m%d%H')"
zip_output="$(cd "$project_root" && "$ROOT/bin/create-delivery" --zip --overwrite)"
zip_name="$(printf '%s\n' "$zip_output" | sed -n 's/^ZIP:[[:space:]]*//p')"
zip_file="$delivery/$zip_name"

assert_file_exists "$zip_file"
case "$zip_name" in
    blue-sky-rev-01-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].zip)
        pass 'ZIP name includes project, revision, and local timestamp'
        ;;
    *) fail "unexpected timestamped ZIP name: $zip_name" ;;
esac
zip_local_hour="$(printf '%s\n' "$zip_name" | sed -n 's/^blue-sky-rev-01-\([0-9][0-9]*\)\.zip$/\1/p' | cut -c 1-10)"
assert_eq "$expected_local_hour" "$zip_local_hour" \
    'ZIP timestamp uses the configured local timezone'
assert_file_exists "$delivery/Blue Sky Main Mix.wav"
assert_json_eq "$expected_created_with" "$dm" '.metadata.created_with' \
    'delivery creator release'
assert_json_eq '1.1.0' "$dm" '.metadata.schema_version' \
    'delivery retains v1.1 schema version'
assert_json_eq 'jl-mixing 1.1.0' "$project_manifest" '.metadata.created_with' \
    'existing project retains original creator provenance'
assert_contains "$(cat "$delivery/Delivery_Notes.md")" 'Final client notes' \
    'working delivery retains edited notes'
assert_eq '0' "$(jq '[.files[] | select(.path|endswith(".zip"))] | length' "$dm")" \
    'ZIP excluded from manifest'

# Python's standard-library ZIP reader keeps this test independent of an unzip
# executable while verifying the exact archived notes content and file list.
zip_inventory="$(python3 - "$zip_file" <<'PY_ZIP_LIST'
from pathlib import Path
from zipfile import ZipFile
import sys
with ZipFile(Path(sys.argv[1])) as archive:
    print("\n".join(sorted(archive.namelist())))
PY_ZIP_LIST
)"
assert_contains "$zip_inventory" 'Delivery_Notes.md' 'ZIP contains delivery notes'
assert_contains "$zip_inventory" 'Blue Sky Main Mix.wav' 'ZIP contains selected audio'
assert_contains "$zip_inventory" 'client-reference.pdf' \
    'ZIP preserves broad current-content behavior'
case "$zip_inventory" in
    *'-rev-'*.zip*) fail 'ZIP must not contain a prior generated ZIP' ;;
    *) pass 'ZIP excludes generated delivery archives' ;;
esac
zip_notes="$(python3 - "$zip_file" <<'PY_ZIP_NOTES'
from pathlib import Path
from zipfile import ZipFile
import sys
with ZipFile(Path(sys.argv[1])) as archive:
    matches = [name for name in archive.namelist() if name.endswith('/Delivery_Notes.md') or name == 'Delivery_Notes.md']
    if len(matches) != 1:
        raise SystemExit(f"expected one Delivery_Notes.md, found {len(matches)}")
    print(archive.read(matches[0]).decode('utf-8'))
PY_ZIP_NOTES
)"
assert_contains "$zip_notes" 'Final client notes' 'ZIP contains edited delivery notes'

# Adding a new managed delivered path is supported by overwrite. The rebuilt
# ZIP must reflect the current managed delivery while preserving edited notes.
printf 'instrumental\n' > "$revision/Blue Sky Instrumental.wav"
changed_zip_output="$(cd "$project_root" && "$ROOT/bin/create-delivery" --zip --overwrite)"
changed_zip_name="$(printf '%s\n' "$changed_zip_output" | sed -n 's/^ZIP:[[:space:]]*//p')"
changed_zip_file="$delivery/$changed_zip_name"
assert_file_exists "$changed_zip_file"
assert_file_exists "$delivery/Blue Sky Instrumental.wav"
assert_contains "$(cat "$delivery/Delivery_Notes.md")" 'Final client notes' \
    'changed-path ZIP overwrite preserves edited notes'
changed_zip_inventory="$(python3 - "$changed_zip_file" <<'PY_ZIP_CHANGED_LIST'
from pathlib import Path
from zipfile import ZipFile
import sys
with ZipFile(Path(sys.argv[1])) as archive:
    print("\n".join(sorted(archive.namelist())))
PY_ZIP_CHANGED_LIST
)"
assert_contains "$changed_zip_inventory" 'Blue Sky Instrumental.wav' \
    'changed-path ZIP overwrite contains new managed file'
assert_contains "$changed_zip_inventory" 'Blue Sky Main Mix.wav' \
    'changed-path ZIP overwrite retains current managed file'
changed_zip_notes="$(python3 - "$changed_zip_file" <<'PY_ZIP_CHANGED_NOTES'
from pathlib import Path
from zipfile import ZipFile
import sys
with ZipFile(Path(sys.argv[1])) as archive:
    matches = [name for name in archive.namelist() if name.endswith('/Delivery_Notes.md') or name == 'Delivery_Notes.md']
    if len(matches) != 1:
        raise SystemExit(f"expected one Delivery_Notes.md, found {len(matches)}")
    print(archive.read(matches[0]).decode('utf-8'))
PY_ZIP_CHANGED_NOTES
)"
assert_contains "$changed_zip_notes" 'Final client notes' \
    'changed-path ZIP overwrite includes edited notes'

echo "[OK] create-delivery ZIP ($TEST_COUNT assertions)"
