#!/usr/bin/env bash
# Portable naming helpers for IDs, folders, DAW projects, and deliverables.
#
# The routines avoid Bash 4 features and sanitize user-controlled components
# before they become filesystem names.
if [ "${JL_MIXING_NAMING_LOADED:-0}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi
JL_MIXING_NAMING_LOADED=1

JL_NAMING_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$JL_NAMING_LIB_DIR/common.sh"

# Best-effort transliteration to ASCII using iconv when available.
jl_transliterate_ascii() {
    local value
    value="$1"
    if jl_command_exists iconv; then
        printf '%s' "$value" | iconv -f UTF-8 -t ASCII//TRANSLIT 2>/dev/null || printf '%s' "$value"
    else
        printf '%s' "$value"
    fi
}

# Convert user text into a lowercase hyphenated stable identifier.
jl_slugify() {
    local value
    value="$(jl_transliterate_ascii "$1")"
    printf '%s' "$value" |
        tr '[:upper:]' '[:lower:]' |
        sed 's/[^a-z0-9][^a-z0-9]*/-/g;s/^-//;s/-$//'
}

# Convert a slug into a readable title-cased default name.
jl_title_from_slug() {
    local slug
    slug="$1"
    printf '%s' "$slug" | tr '-' ' ' | awk '{
        for (i = 1; i <= NF; i++) {
            $i = toupper(substr($i, 1, 1)) substr($i, 2)
        }
        print
    }'
}

# Remove unsafe filename characters and normalize whitespace.
jl_sanitize_component() {
    local value
    value="$1"
    printf '%s' "$value" |
        tr '\r\n\t' '   ' |
        sed 's#[/:*?"<>|]#-#g;s/[[:space:]][[:space:]]*/ /g;s/^[[:space:].-]*//;s/[[:space:].-]*$//'
}

# Format a zero-padded revision folder name.
jl_revision_name() {
    local number prefix padding
    number="$1"
    prefix="${2:-Revision_}"
    padding="${3:-2}"
    printf '%s%0*d\n' "$prefix" "$padding" "$number"
}

# Build the readable DAW project name from artist and project.
jl_daw_project_name() {
    local artist project
    artist="$(jl_sanitize_component "$1")"
    project="$(jl_sanitize_component "$2")"
    printf '%s - %s\n' "$artist" "$project"
}

# Build a deliverable filename stem from artist, project, and label.
jl_deliverable_name() {
    local artist project deliverable extension
    artist="$(jl_sanitize_component "$1")"
    project="$(jl_sanitize_component "$2")"
    deliverable="$(jl_sanitize_component "$3")"
    extension="${4:-wav}"
    extension="$(printf '%s' "$extension" | sed 's/^\.//')"
    printf '%s - %s - %s.%s\n' "$artist" "$project" "$deliverable" "$extension"
}

# Prefix a deliverable name so working prints are excluded from delivery.
jl_working_print_name() {
    local prefix artist project label extension
    prefix="$1"
    artist="$2"
    project="$3"
    label="$4"
    extension="${5:-wav}"
    printf '%s%s\n' "$prefix" "$(jl_deliverable_name "$artist" "$project" "$label" "$extension")"
}

# Replace supported naming tokens in a configured pattern.
jl_expand_naming_pattern() {
    local pattern artist project deliverable result
    pattern="$1"
    artist="$2"
    project="$3"
    deliverable="${4:-}"
    result="$pattern"
    result="$(printf '%s' "$result" | sed "s/{{ARTIST}}/$(printf '%s' "$artist" | sed 's/[&|]/\\&/g')/g")"
    result="$(printf '%s' "$result" | sed "s/{{PROJECT_NAME}}/$(printf '%s' "$project" | sed 's/[&|]/\\&/g')/g")"
    result="$(printf '%s' "$result" | sed "s/{{DELIVERABLE}}/$(printf '%s' "$deliverable" | sed 's/[&|]/\\&/g')/g")"
    printf '%s\n' "$result"
}

# Return a Unicode-aware case-folded representation for deterministic
# case-insensitive collision checks on both macOS and Linux.
jl_name_casefold() {
    local value
    value="$1"
    jl_require_command python3 "Python 3 is required for portable name handling." || return $?
    python3 - "$value" <<'PY_CASEFOLD'
import sys
print(sys.argv[1].casefold())
PY_CASEFOLD
}

# Return success when a component is a Windows-reserved device name. These
# names are rejected on every supported platform so a workspace can be copied
# safely between macOS, Linux, and Windows filesystems.
jl_name_is_reserved_component() {
    local value base upper
    value="$1"
    base="${value%%.*}"
    upper="$(printf '%s' "$base" | tr '[:lower:]' '[:upper:]')"
    case "$upper" in
        CON|PRN|AUX|NUL|CLOCK\$|COM[1-9]|LPT[1-9]) return 0 ;;
        *) return 1 ;;
    esac
}

# Convert a display name into a readable, cross-platform folder component.
# Unsafe separators and control characters become a spaced hyphen, repeated
# whitespace is collapsed, and trailing spaces/periods are removed.
jl_sanitize_folder_name() {
    local value result
    value="$1"
    jl_require_command python3 "Python 3 is required for portable folder-name sanitization." || return $?

    result="$(python3 - "$value" <<'PY_FOLDER_NAME'
import re
import sys
import unicodedata

value = unicodedata.normalize("NFC", sys.argv[1])
characters = []
for character in value:
    if ord(character) < 32 or ord(character) == 127:
        characters.append(" ")
    elif character in '/\\:*?"<>|':
        characters.append(" - ")
    else:
        characters.append(character)
result = "".join(characters)
result = re.sub(r"\s+", " ", result).strip()
result = re.sub(r"(?:\s*-\s*)+", " - ", result).strip()
result = result.strip(" .-")
print(result)
PY_FOLDER_NAME
)" || return $?

    if [ -z "$result" ]; then
        jl_error "Display name does not produce a usable folder name."
        return "$JL_EXIT_VALIDATION"
    fi
    if [ "$result" = . ] || [ "$result" = .. ] || jl_name_is_reserved_component "$result"; then
        jl_error "Reserved folder name is not allowed: $result"
        return "$JL_EXIT_VALIDATION"
    fi

    printf '%s\n' "$result"
}

# Derive the default immutable project ID from a human-readable project name.
# The result is deterministic and never receives an automatic numeric suffix.
jl_project_id_from_name() {
    local project_name project_id
    project_name="$1"
    project_id="$(jl_slugify "$project_name")"
    if [ -z "$project_id" ]; then
        jl_error "Project name does not produce a usable project ID."
        return "$JL_EXIT_VALIDATION"
    fi
    printf '%s\n' "$project_id"
}

# Validate that a list of values is unique under Unicode case folding. Values
# are supplied as positional arguments and are reported exactly as received.
jl_name_assert_case_insensitive_unique() {
    local status
    jl_require_command python3 "Python 3 is required for portable collision checks." || return $?
    if python3 - "$@" <<'PY_UNIQUE_NAMES'
import sys

seen = {}
for value in sys.argv[1:]:
    key = value.casefold()
    if key in seen:
        print(
            f"Case-insensitive collision: {seen[key]!r} and {value!r}",
            file=sys.stderr,
        )
        raise SystemExit(5)
    seen[key] = value
raise SystemExit(0)
PY_UNIQUE_NAMES
    then
        return 0
    else
        status=$?
    fi
    case "$status" in
        5) return "$JL_EXIT_VALIDATION" ;;
        *) return "$JL_EXIT_GENERAL" ;;
    esac
}
