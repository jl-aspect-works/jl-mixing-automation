#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
require_test_command python3
require_test_command jq

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
revision="$tmp/Revision_01"
delivery="$tmp/05_Final_Delivery"
stage="$tmp/stage"
mkdir -p "$revision" "$delivery/Stems" "$stage"
printf '# Delivery Notes\nuser text\n' > "$delivery/Delivery_Notes.md"
printf a > "$revision/Song Main Mix.wav"
printf b > "$revision/Song Instrumental.wav"
printf c > "$revision/Song a-cappella.wav"
printf d > "$revision/Song TV Mix.wav"
printf e > "$revision/Song Performance Mix.wav"
printf f > "$revision/Song Master.wav"
printf g > "$revision/Song Stem Drums.wav"
printf h > "$revision/Custom_Final.wav"
printf i > "$revision/mastering-notes.pdf"
printf j > "$revision/WORK test.wav"
printf '# Revision Notes\n' > "$revision/Revision_Notes.md"
cat > "$tmp/project.json" <<'JSON'
{
  "metadata":{"document_id":"44444444-4444-4444-8444-444444444444"},
  "project_id":"blue-sky","project_name":"Blue Sky",
  "client":{"client_document_id":"22222222-2222-4222-8222-222222222222","client_id":"acme"},
  "delivery":{"method":"Cloud transfer","requested_deliverables":["main_mix","instrumental"]},
  "state":{"approved_revision":1},
  "revisions":[{"number":1,"revision_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","description":"Final","approval":{"approved_at":"2030-01-01T00:00:00Z","approved_by":"Client"}}]
}
JSON

python3 "$ROOT/tools/build-delivery.py" plan \
  --revision-dir "$revision" --delivery-dir "$delivery" \
  --project-manifest "$tmp/project.json" --mode default \
  --working-prefix 'WORK ' --project-zip-name blue-sky-delivery.zip \
  --output "$tmp/plan.json"

assert_json_eq 'main_mix' "$tmp/plan.json" '.selected[]|select(.name=="Song Main Mix.wav")|.deliverable_type' 'main mix classification'
assert_json_eq 'instrumental' "$tmp/plan.json" '.selected[]|select(.name=="Song Instrumental.wav")|.deliverable_type' 'instrumental classification'
assert_json_eq 'acapella' "$tmp/plan.json" '.selected[]|select(.name=="Song a-cappella.wav")|.deliverable_type' 'acapella classification'
assert_json_eq 'tv_mix' "$tmp/plan.json" '.selected[]|select(.name=="Song TV Mix.wav")|.deliverable_type' 'TV mix classification'
assert_json_eq 'performance_mix' "$tmp/plan.json" '.selected[]|select(.name=="Song Performance Mix.wav")|.deliverable_type' 'performance classification'
assert_json_eq 'master' "$tmp/plan.json" '.selected[]|select(.name=="Song Master.wav")|.deliverable_type' 'master classification'
assert_json_eq 'stems' "$tmp/plan.json" '.selected[]|select(.name=="Song Stem Drums.wav")|.deliverable_type' 'stem classification'
assert_json_eq 'unclassified' "$tmp/plan.json" '.selected[]|select(.name=="Custom_Final.wav")|.deliverable_type' 'custom naming unclassified'
assert_json_eq 'unclassified' "$tmp/plan.json" '.selected[]|select(.name=="mastering-notes.pdf")|.deliverable_type' 'whole-word matching avoids mastering false positive'
assert_eq '0' "$(jq '[.selected[]|select(.name=="WORK test.wav")]|length' "$tmp/plan.json")" 'working prefix excluded'
assert_eq '0' "$(jq '[.selected[]|select(.name=="Revision_Notes.md")]|length' "$tmp/plan.json")" 'revision notes excluded'

python3 "$ROOT/tools/build-delivery.py" build \
  --plan "$tmp/plan.json" --project-manifest "$tmp/project.json" \
  --delivery-dir "$delivery" --stage-dir "$stage" \
  --delivery-notes-template "$ROOT/templates/Delivery_Notes.md" \
  --document-id 66666666-6666-4666-8666-666666666666 \
  --created-with 'jl-mixing 1.1.0' --created-at 2030-01-02T00:00:00Z \
  --project-zip-name blue-sky-delivery.zip
assert_file_exists "$stage/delivery-manifest.json"
assert_file_exists "$stage/Stems/Song Stem Drums.wav"
assert_contains "$(cat "$stage/Delivery_Notes.md")" 'user text' 'default build preserves notes'
assert_eq '64' "$(jq -r '.files[0].sha256|length' "$stage/delivery-manifest.json")" 'build records hash'
assert_eq '9' "$(jq '.files|length' "$stage/delivery-manifest.json")" 'all selected regular files inventoried'

# Overwrite requires the same case-insensitive delivery path set.
rm -rf "$delivery"
cp -R "$stage" "$delivery"
python3 "$ROOT/tools/build-delivery.py" plan \
  --revision-dir "$revision" --delivery-dir "$delivery" \
  --project-manifest "$tmp/project.json" --mode overwrite \
  --working-prefix 'WORK ' --project-zip-name blue-sky-delivery.zip \
  --output "$tmp/overwrite-plan.json"
assert_eq '9' "$(jq '.selected|length' "$tmp/overwrite-plan.json")" 'same-shape overwrite accepted'
mv "$revision/Custom_Final.wav" "$revision/Custom_Renamed.wav"
assert_failure 'changed overwrite path set rejected' python3 "$ROOT/tools/build-delivery.py" plan \
  --revision-dir "$revision" --delivery-dir "$delivery" --project-manifest "$tmp/project.json" \
  --mode overwrite --working-prefix 'WORK ' --project-zip-name blue-sky-delivery.zip \
  --output "$tmp/bad-overwrite.json"
mv "$revision/Custom_Renamed.wav" "$revision/Custom_Final.wav"

# Clean planning lists arbitrary content and clean building recreates notes.
printf untracked > "$delivery/untracked.bin"
python3 "$ROOT/tools/build-delivery.py" plan \
  --revision-dir "$revision" --delivery-dir "$delivery" \
  --project-manifest "$tmp/project.json" --mode clean \
  --working-prefix 'WORK ' --project-zip-name blue-sky-delivery.zip \
  --output "$tmp/clean-plan.json"
assert_contains "$(jq -r '.deletions[]' "$tmp/clean-plan.json")" 'untracked.bin' 'clean lists untracked file'
rm -rf "$stage"; mkdir "$stage"
python3 "$ROOT/tools/build-delivery.py" build \
  --plan "$tmp/clean-plan.json" --project-manifest "$tmp/project.json" \
  --delivery-dir "$delivery" --stage-dir "$stage" \
  --delivery-notes-template "$ROOT/templates/Delivery_Notes.md" \
  --document-id 77777777-7777-4777-8777-777777777777 \
  --created-with 'jl-mixing 1.1.0' --created-at 2030-01-03T00:00:00Z \
  --project-zip-name blue-sky-delivery.zip
assert_eq '# Delivery Notes' "$(sed -n '1p' "$stage/Delivery_Notes.md")" 'clean recreates notes template'
assert_path_not_exists "$stage/untracked.bin"

# Source boundaries reject symlinks and subdirectories.
mkdir "$revision/Nested"
assert_failure 'source subdirectory rejected' python3 "$ROOT/tools/build-delivery.py" plan \
  --revision-dir "$revision" --delivery-dir "$delivery" --project-manifest "$tmp/project.json" \
  --mode clean --project-zip-name blue-sky-delivery.zip --output "$tmp/bad.json"
rmdir "$revision/Nested"
ln -s "$revision/Song Main Mix.wav" "$revision/linked.wav"
assert_failure 'source symlink rejected' python3 "$ROOT/tools/build-delivery.py" plan \
  --revision-dir "$revision" --delivery-dir "$delivery" --project-manifest "$tmp/project.json" \
  --mode clean --project-zip-name blue-sky-delivery.zip --output "$tmp/bad.json"

echo "[OK] build-delivery helper ($TEST_COUNT assertions)"
