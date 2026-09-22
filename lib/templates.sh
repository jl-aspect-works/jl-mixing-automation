#!/usr/bin/env bash
# Text/JSON template rendering and managed Markdown section replacement.
#
# Python is used for literal replacement, UTF-8 validation, and escaping so
# user values cannot corrupt JSON or be interpreted as regular expressions.
if [ "${JL_MIXING_TEMPLATES_LOADED:-0}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi
JL_MIXING_TEMPLATES_LOADED=1

JL_TEMPLATES_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$JL_TEMPLATES_LIB_DIR/common.sh"
# shellcheck source=lib/filesystem.sh
. "$JL_TEMPLATES_LIB_DIR/filesystem.sh"

# Render a UTF-8 text/Markdown template from TOKEN/VALUE pairs without
# overwriting output. Generated text always ends with exactly one final newline
# boundary, while intentional interior whitespace remains unchanged.
jl_template_render() {
    local template_file output_file temp_file
    template_file="$1"
    output_file="$2"
    shift 2

    [ -f "$template_file" ] || {
        jl_error "Template not found: $template_file"
        return "$JL_EXIT_VALIDATION"
    }
    if [ $(( $# % 2 )) -ne 0 ]; then
        jl_error "Template values must be supplied as TOKEN VALUE pairs."
        return "$JL_EXIT_ARGUMENTS"
    fi
    jl_require_command python3 "Python 3 is required for template rendering." || return $?
    jl_fs_assert_mutable_path "$output_file" || return $?

    temp_file="$(jl_mktemp_file_near "$output_file")" || return $?
    if ! python3 - "$template_file" "$temp_file" "${JL_TEMPLATE_ALLOW_UNRESOLVED:-0}" "$@" <<'PY_TEMPLATE'
from pathlib import Path
import re
import sys

template_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
allow_unresolved = sys.argv[3] == "1"
values = sys.argv[4:]

# Explicit UTF-8 reads reject malformed templates rather than relying on the
# host locale. Literal replacement never interprets values as regular syntax.
text = template_path.read_text(encoding="utf-8")
for index in range(0, len(values), 2):
    token = values[index]
    value = values[index + 1]
    text = text.replace("{{" + token + "}}", value)

unresolved = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", text)))
if unresolved and not allow_unresolved:
    print("Unresolved template tokens: " + ", ".join(unresolved), file=sys.stderr)
    raise SystemExit(5)

if not text.endswith("\n"):
    text += "\n"
with output_path.open("w", encoding="utf-8", newline="\n") as output_file:
    output_file.write(text)
PY_TEMPLATE
    then
        rm -f "$temp_file"
        jl_error "Template rendering failed: $template_file"
        return "$JL_EXIT_VALIDATION"
    fi

    if [ -e "$output_file" ] || [ -L "$output_file" ]; then
        rm -f "$temp_file"
        jl_error "Refusing to overwrite existing output: $output_file"
        return "$JL_EXIT_UNSAFE"
    fi

    mkdir -p "$(dirname "$output_file")"
    chmod 644 "$temp_file"
    mv "$temp_file" "$output_file"
}

# Validate that a Markdown document contains exactly one ordered marker pair.
# Missing, duplicate, nested, and reversed markers are rejected explicitly.
jl_markdown_validate_managed_section() {
    local markdown_file begin_marker end_marker
    markdown_file="$1"
    begin_marker="$2"
    end_marker="$3"

    [ -f "$markdown_file" ] && [ ! -L "$markdown_file" ] || {
        jl_error "Markdown file not found or unsafe: $markdown_file"
        return "$JL_EXIT_VALIDATION"
    }
    jl_require_command python3 "Python 3 is required for managed Markdown validation." || return $?

    if ! python3 - "$markdown_file" "$begin_marker" "$end_marker" <<'PY_VALIDATE_MARKERS'
from pathlib import Path
import sys

path = Path(sys.argv[1])
begin = sys.argv[2].encode("utf-8")
end = sys.argv[3].encode("utf-8")
text = path.read_bytes()

try:
    text.decode("utf-8")
except UnicodeDecodeError as error:
    print(f"Markdown is not valid UTF-8: {error}", file=sys.stderr)
    raise SystemExit(5)

begin_count = text.count(begin)
end_count = text.count(end)
if begin_count != 1 or end_count != 1:
    print(
        "Managed-section markers must each appear exactly once "
        f"(begin={begin_count}, end={end_count}).",
        file=sys.stderr,
    )
    raise SystemExit(5)

begin_index = text.find(begin)
end_index = text.find(end)
if begin_index >= end_index:
    print("Managed-section markers are reversed.", file=sys.stderr)
    raise SystemExit(5)

# A marker token occurring inside the selected interior would have increased
# the count above one; the explicit ordered check completes nested validation.
raise SystemExit(0)
PY_VALIDATE_MARKERS
    then
        jl_error "Invalid managed Markdown markers: $markdown_file"
        return "$JL_EXIT_VALIDATION"
    fi
}

# Replace exactly one marked Markdown region while preserving every byte before
# the opening marker and after the closing marker. Replacement content must be
# valid UTF-8 and is normalized only inside the managed region.
jl_markdown_replace_managed_section() {
    local markdown_file begin_marker end_marker replacement_file temp_file
    markdown_file="$1"
    begin_marker="$2"
    end_marker="$3"
    replacement_file="$4"

    [ -f "$replacement_file" ] && [ ! -L "$replacement_file" ] || {
        jl_error "Replacement content not found or unsafe: $replacement_file"
        return "$JL_EXIT_VALIDATION"
    }
    jl_markdown_validate_managed_section "$markdown_file" "$begin_marker" "$end_marker" || return $?
    jl_fs_assert_mutable_path "$markdown_file" || return $?

    temp_file="$(jl_mktemp_file_near "$markdown_file")" || return $?
    if ! python3 - "$markdown_file" "$replacement_file" "$begin_marker" "$end_marker" "$temp_file" <<'PY_MANAGED'
from pathlib import Path
import sys

markdown_path = Path(sys.argv[1])
replacement_path = Path(sys.argv[2])
begin = sys.argv[3].encode("utf-8")
end = sys.argv[4].encode("utf-8")
output_path = Path(sys.argv[5])

text = markdown_path.read_bytes()
replacement_bytes = replacement_path.read_bytes()
try:
    replacement = replacement_bytes.decode("utf-8")
except UnicodeDecodeError as error:
    print(f"Replacement is not valid UTF-8: {error}", file=sys.stderr)
    raise SystemExit(5)

start = text.index(begin) + len(begin)
finish = text.index(end, start)
replacement = replacement.strip("\r\n")
managed = ("\n" + replacement + "\n").encode("utf-8")
new_text = text[:start] + managed + text[finish:]
output_path.write_bytes(new_text)
PY_MANAGED
    then
        rm -f "$temp_file"
        jl_error "Managed Markdown update failed: $markdown_file"
        return "$JL_EXIT_VALIDATION"
    fi

    chmod "$(jl_stat_mode "$markdown_file")" "$temp_file"
    mv "$temp_file" "$markdown_file"
}

# Verify that a rendered template no longer contains documented placeholder
# syntax. This helper can validate staged output independently of rendering.
jl_template_validate_no_placeholders() {
    local file
    file="$1"
    [ -f "$file" ] && [ ! -L "$file" ] || {
        jl_error "Rendered template not found or unsafe: $file"
        return "$JL_EXIT_VALIDATION"
    }
    if grep -Eq '\{\{[A-Z0-9_]+\}\}' "$file"; then
        jl_error "Rendered template contains unresolved placeholders: $file"
        return "$JL_EXIT_VALIDATION"
    fi
}

# Render a JSON text template while escaping replacement values as JSON string
# contents. Templates used with this function must place tokens inside quotes.
jl_template_render_json() {
    local template_file output_file temp_file allow_unresolved
    template_file="$1"
    output_file="$2"
    shift 2

    [ -f "$template_file" ] || {
        jl_error "Template not found: $template_file"
        return "$JL_EXIT_VALIDATION"
    }
    if [ $(( $# % 2 )) -ne 0 ]; then
        jl_error "Template values must be supplied as TOKEN VALUE pairs."
        return "$JL_EXIT_ARGUMENTS"
    fi
    jl_require_command python3 "Python 3 is required for JSON template rendering." || return $?
    jl_fs_assert_mutable_path "$output_file" || return $?

    if [ -e "$output_file" ] || [ -L "$output_file" ]; then
        jl_error "Refusing to overwrite existing output: $output_file"
        return "$JL_EXIT_UNSAFE"
    fi

    temp_file="$(jl_mktemp_file_near "$output_file")" || return $?
    allow_unresolved="${JL_TEMPLATE_ALLOW_UNRESOLVED:-0}"
    if ! python3 - "$template_file" "$temp_file" "$allow_unresolved" "$@" <<'PY_JSON_TEMPLATE'
from pathlib import Path
import json
import re
import sys

template_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
allow_unresolved = sys.argv[3] == "1"
values = sys.argv[4:]
text = template_path.read_text(encoding="utf-8")

for index in range(0, len(values), 2):
    token = values[index]
    value = values[index + 1]
    escaped_content = json.dumps(value, ensure_ascii=False)[1:-1]
    text = text.replace("{{" + token + "}}", escaped_content)

unresolved = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", text)))
if unresolved and not allow_unresolved:
    print("Unresolved template tokens: " + ", ".join(unresolved), file=sys.stderr)
    raise SystemExit(5)

json.loads(text)
if not text.endswith("\n"):
    text += "\n"
with output_path.open("w", encoding="utf-8", newline="\n") as output_file:
    output_file.write(text)
PY_JSON_TEMPLATE
    then
        rm -f "$temp_file"
        jl_error "JSON template rendering failed: $template_file"
        return "$JL_EXIT_VALIDATION"
    fi

    mkdir -p "$(dirname "$output_file")"
    chmod 644 "$temp_file"
    mv "$temp_file" "$output_file"
}
