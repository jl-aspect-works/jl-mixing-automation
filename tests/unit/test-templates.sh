#!/usr/bin/env bash
set -eu

# Purpose: Verify text/JSON rendering and managed Markdown replacement safety.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
. "$ROOT/lib/templates.sh"

# Arrange: build an isolated temporary fixture.
tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT
printf 'Hello {{NAME}} from {{PLACE}}\n' > "$tmp/template.txt"
jl_template_render "$tmp/template.txt" "$tmp/output.txt" NAME Jake PLACE Studio
# Assert: verify observable behavior rather than internal implementation.
assert_eq "Hello Jake from Studio" "$(cat "$tmp/output.txt")" "render literal tokens"
assert_failure "unresolved token rejected" jl_template_render "$tmp/template.txt" "$tmp/bad.txt" NAME Jake

# Monterey ships a Python version where Path.write_text() does not accept the
# newline keyword. Keep template rendering on the older-compatible Path.open API.
assert_failure "unsupported Path.write_text newline API is absent" \
    grep -F 'write_text(text, encoding="utf-8", newline=' "$ROOT/lib/templates.sh"

printf '{"name":"{{NAME}}","pattern":"{{PROJECT_NAME}}"}\n' > "$tmp/template.json"
JL_TEMPLATE_ALLOW_UNRESOLVED=1 jl_template_render_json \
    "$tmp/template.json" "$tmp/output.json" NAME 'Jake "Mix"'
json_name="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["name"])' "$tmp/output.json")"
assert_eq 'Jake "Mix"' "$json_name" "JSON template escapes string values"
assert_contains "$(cat "$tmp/output.json")" '{{PROJECT_NAME}}' "intentional naming token preserved"
cat > "$tmp/report.md" <<'EOF'
# Report

Human notes stay here.

<!-- BEGIN AUTO -->
old
<!-- END AUTO -->

Footer stays here.
EOF
printf 'new managed content\n' > "$tmp/replacement.md"
jl_markdown_replace_managed_section "$tmp/report.md" '<!-- BEGIN AUTO -->' '<!-- END AUTO -->' "$tmp/replacement.md"
content="$(cat "$tmp/report.md")"
assert_contains "$content" "Human notes stay here." "human notes preserved"
assert_contains "$content" "new managed content" "managed section replaced"
assert_contains "$content" "Footer stays here." "footer preserved"

# Generated Markdown/text always receives a final newline.
last_byte="$(tail -c 1 "$tmp/output.txt" | od -An -t u1 | tr -d ' ')"
assert_eq "10" "$last_byte" "rendered text has final newline"

cat > "$tmp/byte-report.md" <<'EOF_BYTES'
PREFIX-style literal
<!-- BEGIN AUTO -->
old content
<!-- END AUTO -->
SUFFIX without rewrite
EOF_BYTES
python3 - "$tmp/byte-report.md" "$tmp/prefix.bin" "$tmp/suffix.bin" <<'PY_SPLIT'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_bytes()
begin = b"<!-- BEGIN AUTO -->"
end = b"<!-- END AUTO -->"
Path(sys.argv[2]).write_bytes(text[: text.index(begin) + len(begin)])
Path(sys.argv[3]).write_bytes(text[text.index(end):])
PY_SPLIT
printf 'replacement bytes
' > "$tmp/byte-replacement.md"
jl_markdown_replace_managed_section \
    "$tmp/byte-report.md" '<!-- BEGIN AUTO -->' '<!-- END AUTO -->' "$tmp/byte-replacement.md"
python3 - "$tmp/byte-report.md" "$tmp/prefix.bin" "$tmp/suffix.bin" <<'PY_COMPARE'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_bytes()
prefix = Path(sys.argv[2]).read_bytes()
suffix = Path(sys.argv[3]).read_bytes()
raise SystemExit(0 if text.startswith(prefix) and text.endswith(suffix) else 1)
PY_COMPARE
pass "bytes outside managed section preserved"

printf '<!-- END AUTO -->
text
<!-- BEGIN AUTO -->
' > "$tmp/reversed.md"
assert_failure "reversed markers rejected" \
    jl_markdown_validate_managed_section "$tmp/reversed.md" '<!-- BEGIN AUTO -->' '<!-- END AUTO -->'
printf '<!-- BEGIN AUTO -->
<!-- BEGIN AUTO -->
<!-- END AUTO -->
' > "$tmp/duplicate.md"
assert_failure "duplicate markers rejected" \
    jl_markdown_validate_managed_section "$tmp/duplicate.md" '<!-- BEGIN AUTO -->' '<!-- END AUTO -->'
printf 'no markers
' > "$tmp/missing.md"
assert_failure "missing markers rejected" \
    jl_markdown_validate_managed_section "$tmp/missing.md" '<!-- BEGIN AUTO -->' '<!-- END AUTO -->'
printf 'Rendered {{LEFT}}
' > "$tmp/unresolved.txt"
assert_failure "unresolved staged placeholder rejected" \
    jl_template_validate_no_placeholders "$tmp/unresolved.txt"
printf 'Rendered complete
' > "$tmp/resolved.txt"
assert_success "resolved staged template accepted" \
    jl_template_validate_no_placeholders "$tmp/resolved.txt"
echo "[OK] templates.sh ($TEST_COUNT assertions)"
