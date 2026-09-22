#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/integration/integration-helper.sh"
require_test_command jq
require_test_command python3
python3 -c 'import jsonschema' >/dev/null 2>&1 || { echo '[SKIP] create-delivery clean requires jsonschema.'; exit 0; }

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
studio_root="$tmp/studio"
project_root="$(fixture_v11_approved_project "$studio_root")"
manifest="$project_root/00_Admin/project-manifest.json"
revision="$project_root/04_Revisions/Revision_01"
delivery="$project_root/05_Final_Delivery"
dm="$delivery/delivery-manifest.json"
printf 'main-data\n' > "$revision/Blue Sky Main Mix.wav"
printf 'remove me\n' > "$delivery/untracked.txt"
printf '{bad json\n' > "$dm"

(cd "$project_root" && "$ROOT/bin/create-delivery" --clean >/dev/null)
assert_path_not_exists "$delivery/untracked.txt"
assert_json_eq 'mixing-delivery' "$dm" '.metadata.schema' 'clean repairs malformed prior package'
assert_eq '# Delivery Notes' "$(sed -n '1p' "$delivery/Delivery_Notes.md")" 'clean recreates notes template'

cp "$manifest" "$tmp/project-before.json"
cp "$dm" "$tmp/delivery-before.json"
printf 'main-data-v2\n' > "$revision/Blue Sky Main Mix.wav"
assert_failure 'transaction failure rolls back package and manifest' \
    env JL_MIXING_FAIL_AT=after-coordinated-directory JL_MIXING_HOME="$ROOT" JL_MIXING_ROOT="$studio_root" \
        "$ROOT/bin/create-delivery" --project "$project_root" --clean
assert_same_bytes "$tmp/project-before.json" "$manifest"
assert_same_bytes "$tmp/delivery-before.json" "$dm"

echo "[OK] create-delivery clean ($TEST_COUNT assertions)"
