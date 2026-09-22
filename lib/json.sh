#!/usr/bin/env bash
# JSON parsing, atomic mutation, schema identity, and schema validation helpers.
#
# jq handles reads and transformations; Python jsonschema performs Draft 2020-12
# validation. All file mutations go through temporary files and atomic replace.
if [ "${JL_MIXING_JSON_LOADED:-0}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi
JL_MIXING_JSON_LOADED=1

JL_JSON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JL_JSON_REPO_ROOT="$(cd "$JL_JSON_LIB_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
. "$JL_JSON_LIB_DIR/common.sh"
# shellcheck source=lib/platform.sh
. "$JL_JSON_LIB_DIR/platform.sh"
# shellcheck source=lib/filesystem.sh
. "$JL_JSON_LIB_DIR/filesystem.sh"

# Require jq before any JSON operation.
jl_json_require_jq() {
    jl_require_command jq "Install jq before using JL Mixing Automation JSON features."
}

# Return success when a file contains syntactically valid JSON.
jl_json_is_valid() {
    local file
    file="$1"
    [ -f "$file" ] || return 1
    jl_json_require_jq || return $?
    jq empty "$file" >/dev/null 2>&1
}

# Read a required scalar value with jq -e semantics.
jl_json_get() {
    local file filter
    file="$1"
    filter="$2"
    jl_json_require_jq || return $?
    jq -er "$filter" "$file"
}

# Read an optional scalar and return a supplied default when absent or null.
jl_json_get_optional() {
    local file filter default_value value
    file="$1"
    filter="$2"
    default_value="${3:-}"
    jl_json_require_jq || return $?

    value="$(jq -er "$filter // empty" "$file" 2>/dev/null || true)"
    if [ -z "$value" ]; then
        printf '%s\n' "$default_value"
    else
        printf '%s\n' "$value"
    fi
}

# Read a required value while preserving its JSON representation.
jl_json_get_json() {
    local file filter
    file="$1"
    filter="$2"
    jl_json_require_jq || return $?
    jq -e "$filter" "$file"
}

# Apply a jq transformation to a temporary file and atomically replace the original.
jl_json_update() {
    local file filter temp_file
    file="$1"
    filter="$2"
    shift 2

    [ -f "$file" ] || {
        jl_error "JSON file not found: $file"
        return "$JL_EXIT_VALIDATION"
    }
    jl_json_require_jq || return $?
    jl_json_is_valid "$file" || {
        jl_error "Invalid JSON syntax: $file"
        return "$JL_EXIT_VALIDATION"
    }
    jl_fs_assert_mutable_path "$file" || return $?

    temp_file="$(jl_mktemp_file_near "$file")" || return $?
    if ! jq "$@" "$filter" "$file" > "$temp_file"; then
        rm -f "$temp_file"
        jl_error "JSON update failed: $file"
        return "$JL_EXIT_VALIDATION"
    fi

    chmod "$(jl_stat_mode "$file")" "$temp_file"
    mv "$temp_file" "$file"
}

# Set one jq path to a string value.
jl_json_set_string() {
    local file path_expression value
    file="$1"
    path_expression="$2"
    value="$3"
    jl_json_update "$file" "$path_expression = \$jl_value" --arg jl_value "$value"
}

# Set one jq path to a caller-supplied JSON value.
jl_json_set_value() {
    local file path_expression json_value
    file="$1"
    path_expression="$2"
    json_value="$3"
    jl_json_update "$file" "$path_expression = \$jl_value" --argjson jl_value "$json_value"
}

# Delete one jq path atomically.
jl_json_delete() {
    local file path_expression
    file="$1"
    path_expression="$2"
    jl_json_update "$file" "del($path_expression)"
}

# Extract the major component of a semantic schema version.
jl_json_schema_major() {
    local file version
    file="$1"
    version="$(jl_json_get "$file" '.metadata.schema_version')" || return $?
    printf '%s\n' "$version" | cut -d. -f1
}

# Check document schema name and supported major version.
jl_json_require_schema_identity() {
    local file expected_schema expected_major actual_schema actual_major
    file="$1"
    expected_schema="$2"
    expected_major="${3:-1}"

    actual_schema="$(jl_json_get "$file" '.metadata.schema')" || return $?
    actual_major="$(jl_json_schema_major "$file")" || return $?

    if [ "$actual_schema" != "$expected_schema" ]; then
        jl_error "Unexpected schema '$actual_schema'; expected '$expected_schema'."
        return "$JL_EXIT_VALIDATION"
    fi
    if [ "$actual_major" != "$expected_major" ]; then
        jl_error "Unsupported schema major version '$actual_major'; expected '$expected_major'."
        return "$JL_EXIT_VALIDATION"
    fi
}


# Resolve one schema filename from the installed application's local schema set.
# Callers pass a basename such as "project-manifest.schema.json"; path
# separators are rejected so validation can never escape the trusted schema
# directory.
jl_json_schema_path() {
    local schema_name schema_path
    schema_name="$1"

    case "$schema_name" in
        ''|*/*|*'\'*)
            jl_error "Invalid local schema name: $schema_name"
            return "$JL_EXIT_ARGUMENTS"
            ;;
    esac

    schema_path="$JL_JSON_REPO_ROOT/schemas/$schema_name"
    if [ ! -f "$schema_path" ] || [ -L "$schema_path" ]; then
        jl_error "Local JSON Schema not found: $schema_path"
        return "$JL_EXIT_CONFIG"
    fi

    printf '%s
' "$schema_path"
}

# Check a document's exact schema name and schema version. Generic utilities
# may still inspect the schema major, but every v1.1 workflow mutation uses this
# exact identity check.
jl_json_require_exact_schema_identity() {
    local file expected_schema expected_version actual_schema actual_version
    file="$1"
    expected_schema="$2"
    expected_version="$3"

    actual_schema="$(jl_json_get "$file" '.metadata.schema')" || {
        jl_error "Missing or invalid metadata.schema in: $file"
        return "$JL_EXIT_VALIDATION"
    }
    actual_version="$(jl_json_get "$file" '.metadata.schema_version')" || {
        jl_error "Missing or invalid metadata.schema_version in: $file"
        return "$JL_EXIT_VALIDATION"
    }

    if [ "$actual_schema" != "$expected_schema" ]; then
        jl_error "Unexpected schema '$actual_schema'; expected '$expected_schema'."
        return "$JL_EXIT_VALIDATION"
    fi
    if [ "$actual_version" != "$expected_version" ]; then
        jl_error "Unsupported schema version '$actual_version'; expected '$expected_version'."
        return "$JL_EXIT_VALIDATION"
    fi
}

# Require created_with to identify the JL Mixing application release that
# originally created the document. This is provenance metadata, so its release
# version is intentionally independent of metadata.schema_version.
jl_json_require_created_with_semver() {
    local file created_with actual_version
    file="$1"

    created_with="$(jl_json_get "$file" '.metadata.created_with')" || {
        jl_error "Missing or invalid metadata.created_with in: $file"
        return "$JL_EXIT_VALIDATION"
    }

    case "$created_with" in
        'jl-mixing '[0-9]*.[0-9]*.[0-9]*) actual_version="${created_with#jl-mixing }" ;;
        *)
            jl_error "Invalid created_with value '$created_with' in: $file"
            return "$JL_EXIT_VALIDATION"
            ;;
    esac

    # Require semantic version core components while allowing standard
    # prerelease and build metadata suffixes used by release candidates.
    if ! printf '%s\n' "$actual_version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$'; then
        jl_error "Invalid jl-mixing semantic version '$actual_version' in: $file"
        return "$JL_EXIT_VALIDATION"
    fi
}

# Compatibility alias for scripts that sourced the v1.1 library function.
# The expected-version argument is accepted but intentionally ignored because
# creator release provenance no longer determines schema compatibility.
jl_json_require_created_with_series() {
    local file
    file="$1"
    jl_json_require_created_with_semver "$file"
}

# Validate a document against one schema from the installed local schema set,
# then enforce the exact document identity and valid creator release provenance.
jl_json_validate_local_document() {
    local document_file schema_name expected_schema expected_version schema_file
    document_file="$1"
    schema_name="$2"
    expected_schema="$3"
    expected_version="$4"

    schema_file="$(jl_json_schema_path "$schema_name")" || return $?
    jl_json_validate_schema "$schema_file" "$document_file" || return $?
    jl_json_require_exact_schema_identity "$document_file" "$expected_schema" "$expected_version" || return $?
    jl_json_require_created_with_semver "$document_file"
}

# List governing JL Mixing JSON records at their canonical v1.1 locations
# without descending into user-owned audio, DAW, notes, or recall content.
jl_json_governing_files() {
    local studio_root studio_file
    studio_root="$1"

    [ -d "$studio_root" ] || {
        jl_error "Studio root not found: $studio_root"
        return "$JL_EXIT_CONTEXT"
    }

    studio_file="$studio_root/Studio/studio.json"
    if [ -f "$studio_file" ] && [ ! -L "$studio_file" ]; then
        printf '%s\n' "$studio_file"
    fi

    [ -d "$studio_root/Clients" ] || return 0
    find "$studio_root/Clients" -mindepth 2 -maxdepth 2 \
        -type f -name client.json -print
    find "$studio_root/Clients" -mindepth 5 -maxdepth 5 -type f \
        \( -path '*/00_Admin/project-manifest.json' \
           -o -path '*/00_Admin/client-profile-snapshot.json' \
           -o -path '*/05_Final_Delivery/delivery-manifest.json' \) \
        -print
}

# Verify that every governing metadata.document_id and revision_id is unique
# across the studio. Structural schema validation reports missing/invalid UUIDs;
# this helper enforces only the cross-document uniqueness invariant.
jl_json_validate_unique_uuids() {
    local studio_root python_command status
    studio_root="$1"
    python_command="$(jl_json_validator_python)" || {
        jl_error "Python 3 is required for UUID validation."
        return "$JL_EXIT_CONFIG"
    }

    if jl_json_governing_files "$studio_root" | "$python_command" -c '
import json
import sys
from pathlib import Path

seen = {}
failed = False
for raw in sys.stdin:
    path = Path(raw.rstrip("\n"))
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        continue

    values = []
    document_id = document.get("metadata", {}).get("document_id")
    if isinstance(document_id, str) and document_id:
        values.append(("document_id", document_id))
    for revision in document.get("revisions", []):
        if isinstance(revision, dict):
            revision_id = revision.get("revision_id")
            if isinstance(revision_id, str) and revision_id:
                values.append(("revision_id", revision_id))

    for label, value in values:
        key = value.casefold()
        location = f"{path} ({label})"
        if key in seen:
            print(
                f"Duplicate UUID {value}: {seen[key]} and {location}",
                file=sys.stderr,
            )
            failed = True
        else:
            seen[key] = location
raise SystemExit(5 if failed else 0)
'; then
        return 0
    else
        status=$?
    fi

    case "$status" in
        5)
            jl_error "Studio contains duplicate governing UUID values."
            return "$JL_EXIT_VALIDATION"
            ;;
        *)
            jl_error "Unable to validate studio UUIDs: $studio_root"
            return "$JL_EXIT_GENERAL"
            ;;
    esac
}

# Backward-compatible descriptive alias for callers concerned only with the
# document-ID rule. The implementation also catches revision-ID collisions.
jl_json_validate_unique_document_ids() {
    jl_json_validate_unique_uuids "$1"
}

# Check whether a proposed document or revision UUID is available before a new
# governing record is committed. An optional path may be excluded during a
# validated in-place replacement.
jl_json_assert_uuid_available() {
    local studio_root proposed_id exclude_path python_command status
    studio_root="$1"
    proposed_id="$2"
    exclude_path="${3:-}"
    python_command="$(jl_json_validator_python)" || {
        jl_error "Python 3 is required for UUID validation."
        return "$JL_EXIT_CONFIG"
    }

    if jl_json_governing_files "$studio_root" | "$python_command" -c '
import json
import os
import sys
from pathlib import Path

proposed = sys.argv[1].casefold()
exclude = os.path.realpath(sys.argv[2]) if sys.argv[2] else None
for raw in sys.stdin:
    path = Path(raw.rstrip("\n"))
    if exclude and os.path.realpath(path) == exclude:
        continue
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        continue

    values = [document.get("metadata", {}).get("document_id")]
    values.extend(
        revision.get("revision_id")
        for revision in document.get("revisions", [])
        if isinstance(revision, dict)
    )
    if any(isinstance(value, str) and value.casefold() == proposed for value in values):
        print(path, file=sys.stderr)
        raise SystemExit(5)
raise SystemExit(0)
' "$proposed_id" "$exclude_path"; then
        return 0
    else
        status=$?
    fi

    case "$status" in
        5)
            jl_error "UUID already exists in this studio: $proposed_id"
            return "$JL_EXIT_VALIDATION"
            ;;
        *)
            jl_error "Unable to check UUID availability: $proposed_id"
            return "$JL_EXIT_GENERAL"
            ;;
    esac
}

jl_json_assert_document_id_available() {
    jl_json_assert_uuid_available "$@"
}

# Choose the application/private Python interpreter used for schema validation.
jl_json_validator_python() {
    if [ -n "${JL_MIXING_PYTHON:-}" ] && [ -x "$JL_MIXING_PYTHON" ]; then
        printf '%s\n' "$JL_MIXING_PYTHON"
    elif [ -x "$JL_JSON_REPO_ROOT/.venv/bin/python" ]; then
        printf '%s\n' "$JL_JSON_REPO_ROOT/.venv/bin/python"
    elif jl_command_exists python3; then
        command -v python3
    else
        return "$JL_EXIT_CONFIG"
    fi
}

# Validate an instance against a Draft 2020-12 schema.
jl_json_validate_schema() {
    local schema_file document_file python_command
    schema_file="$1"
    document_file="$2"
    python_command="$(jl_json_validator_python)" || {
        jl_error "Python 3 is required for JSON Schema validation."
        return "$JL_EXIT_CONFIG"
    }

    "$python_command" "$JL_JSON_REPO_ROOT/tools/validate-json.py" \
        --strict --schema "$schema_file" --document "$document_file"
}

# Validate multiple schema/document pairs in one Python process. Starting the
# pinned JSON Schema runtime once keeps project-context validation responsive
# while preserving strict local-schema behavior for every document.
jl_json_validate_schema_pairs() {
    local python_command
    local -a validator_args

    if [ "$#" -eq 0 ] || [ $(( $# % 2 )) -ne 0 ]; then
        jl_error "Schema validation requires SCHEMA DOCUMENT pairs."
        return "$JL_EXIT_ARGUMENTS"
    fi
    python_command="$(jl_json_validator_python)" || {
        jl_error "Python 3 is required for JSON Schema validation."
        return "$JL_EXIT_CONFIG"
    }

    validator_args=(--strict)
    while [ "$#" -gt 0 ]; do
        validator_args+=(--schema "$1" --document "$2")
        shift 2
    done
    "$python_command" "$JL_JSON_REPO_ROOT/tools/validate-json.py" \
        "${validator_args[@]}"
}

# Convert a comma-separated string into a compact JSON string array.
# Empty input becomes an empty array. Whitespace around entries is removed.
# Convert a comma-separated string into a trimmed JSON string array.
jl_json_array_from_csv() {
    local csv
    csv="$1"
    jl_json_require_jq || return $?

    if [ -z "$csv" ]; then
        printf '%s\n' '[]'
        return 0
    fi

    printf '%s' "$csv" |
        jq -R -c 'split(",") | map(gsub("^[[:space:]]+|[[:space:]]+$"; "")) | map(select(length > 0))'
}