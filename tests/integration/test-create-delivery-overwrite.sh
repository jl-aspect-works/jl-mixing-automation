#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/integration/integration-helper.sh"
require_test_command jq
require_test_command python3
python3 -c 'import jsonschema' >/dev/null 2>&1 || { echo '[SKIP] create-delivery overwrite requires jsonschema.'; exit 0; }

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
studio_root="$tmp/studio"
project_root="$(fixture_v11_approved_project "$studio_root")"
revision="$project_root/04_Revisions/Revision_01"
delivery="$project_root/05_Final_Delivery"
printf 'main-v1\n' > "$revision/Blue Sky Main Mix.wav"
printf 'custom-v1\n' > "$revision/BlueSky_Custom.wav"
(cd "$project_root" && "$ROOT/bin/create-delivery" >/dev/null)
printf 'user note\n' >> "$delivery/Delivery_Notes.md"
printf 'keep\n' > "$delivery/client-reference.pdf"
printf 'main-v2\n' > "$revision/Blue Sky Main Mix.wav"
(cd "$project_root" && "$ROOT/bin/create-delivery" --overwrite >/dev/null)
assert_contains "$(cat "$delivery/Delivery_Notes.md")" 'user note' 'overwrite preserves delivery notes'
assert_file_exists "$delivery/client-reference.pdf"
assert_contains "$(cat "$delivery/Blue Sky Main Mix.wav")" 'main-v2' 'overwrite replaces tracked file'

mv "$revision/BlueSky_Custom.wav" "$revision/BlueSky_Renamed.wav"
(cd "$project_root" && "$ROOT/bin/create-delivery" --overwrite >/dev/null)
assert_path_not_exists "$delivery/BlueSky_Custom.wav"
assert_file_exists "$delivery/BlueSky_Renamed.wav"
assert_contains "$(cat "$delivery/Delivery_Notes.md")" 'user note' 'changed-path overwrite preserves delivery notes'
assert_file_exists "$delivery/client-reference.pdf"

printf 'untracked\n' > "$delivery/BlueSky_Collision.wav"
mv "$revision/BlueSky_Renamed.wav" "$revision/BlueSky_Collision.wav"
assert_failure 'overwrite rejects collision with untracked destination' \
    env JL_MIXING_HOME="$ROOT" JL_MIXING_ROOT="$studio_root" \
        "$ROOT/bin/create-delivery" --project "$project_root" --overwrite

echo "[OK] create-delivery overwrite ($TEST_COUNT assertions)"
