#!/usr/bin/env bash
# Creation and maintenance of the standard metadata block in JSON documents.
#
# Creation identity is stable. Only last_modified_at changes during updates.
if [ "${JL_MIXING_METADATA_LOADED:-0}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi
JL_MIXING_METADATA_LOADED=1

JL_METADATA_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JL_METADATA_REPO_ROOT="$(cd "$JL_METADATA_LIB_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
. "$JL_METADATA_LIB_DIR/common.sh"
# shellcheck source=lib/json.sh
. "$JL_METADATA_LIB_DIR/json.sh"

# Read the application VERSION file from the resolved installation root.
jl_software_version() {
    local version_file first_line
    version_file="${JL_MIXING_VERSION_FILE:-$JL_METADATA_REPO_ROOT/VERSION}"
    if [ ! -f "$version_file" ]; then
        jl_error "VERSION file not found: $version_file"
        return "$JL_EXIT_CONFIG"
    fi
    first_line="$(sed -n '1p' "$version_file")"
    jl_assert_nonempty "$first_line" "software version" || return $?
    if ! printf '%s\n' "$first_line" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$'; then
        jl_error "Invalid application version '$first_line' in: $version_file"
        return "$JL_EXIT_CONFIG"
    fi
    printf '%s\n' "$first_line"
}

# Metadata provenance uses the same release-version grammar as VERSION. This
# deliberately permits release-candidate/build suffixes without coupling
# application provenance to metadata.schema_version.
jl_json_require_created_with_semver() {
    local file created_with actual_version
    file="$1"

    created_with="$(jl_json_get "$file" '.metadata.created_with')" || {
        jl_error "Missing or invalid metadata.created_with in: $file"
        return "$JL_EXIT_VALIDATION"
    }
    case "$created_with" in
        'jl-mixing '*) actual_version="${created_with#jl-mixing }" ;;
        *)
            jl_error "Invalid created_with value '$created_with' in: $file"
            return "$JL_EXIT_VALIDATION"
            ;;
    esac
    if ! printf '%s\n' "$actual_version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$'; then
        jl_error "Invalid jl-mixing semantic version '$actual_version' in: $file"
        return "$JL_EXIT_VALIDATION"
    fi
}

# Build release-provenance metadata independently of schema_version.
jl_created_with() {
    local software_version
    software_version="$(jl_software_version)" || return $?
    printf 'jl-mixing %s\n' "$software_version"
}

# Refresh only last_modified_at on an existing mutable v1.1 document.
jl_metadata_touch() {
    local file timestamp
    file="$1"
    timestamp="${2:-$(jl_now_iso8601)}"
    jl_json_set_string "$file" '.metadata.last_modified_at' "$timestamp"
}

# Create the v1.1 metadata shape used by mutable studio, client, and project
# documents. created_by was removed; last_modified_at starts equal to created_at.
jl_metadata_create_v11_mutable() {
    local schema_name schema_version document_id timestamp created_with
    schema_name="$1"
    schema_version="${2:-1.1.0}"
    document_id="${3:-$(jl_uuid)}"
    timestamp="${4:-$(jl_now_iso8601)}"
    created_with="$(jl_created_with)" || return $?

    jl_json_require_jq || return $?
    jq -n \
        --arg schema "$schema_name" \
        --arg schema_version "$schema_version" \
        --arg document_id "$document_id" \
        --arg created_with "$created_with" \
        --arg created_at "$timestamp" \
        '{
            schema: $schema,
            schema_version: $schema_version,
            document_id: $document_id,
            created_with: $created_with,
            created_at: $created_at,
            last_modified_at: $created_at
        }'
}

# Create the v1.1 metadata shape used by immutable snapshots and delivery
# manifests. These records intentionally have no last_modified_at field.
jl_metadata_create_v11_immutable() {
    local schema_name schema_version document_id timestamp created_with
    schema_name="$1"
    schema_version="${2:-1.1.0}"
    document_id="${3:-$(jl_uuid)}"
    timestamp="${4:-$(jl_now_iso8601)}"
    created_with="$(jl_created_with)" || return $?

    jl_json_require_jq || return $?
    jq -n \
        --arg schema "$schema_name" \
        --arg schema_version "$schema_version" \
        --arg document_id "$document_id" \
        --arg created_with "$created_with" \
        --arg created_at "$timestamp" \
        '{
            schema: $schema,
            schema_version: $schema_version,
            document_id: $document_id,
            created_with: $created_with,
            created_at: $created_at
        }'
}

# Validate the common v1.1 schema contract before a command uses a governing
# document. The final argument is either mutable or immutable.
jl_metadata_validate_v11() {
    local file expected_schema mutability field value
    file="$1"
    expected_schema="$2"
    mutability="$3"

    jl_json_require_exact_schema_identity "$file" "$expected_schema" 1.1.0 || return $?
    jl_json_require_created_with_semver "$file" || return $?

    for field in document_id created_with created_at; do
        value="$(jl_json_get_optional "$file" ".metadata.$field" '')"
        if [ -z "$value" ]; then
            jl_error "Missing metadata field '$field' in $file"
            return "$JL_EXIT_VALIDATION"
        fi
    done

    case "$mutability" in
        mutable)
            value="$(jl_json_get_optional "$file" '.metadata.last_modified_at' '')"
            [ -n "$value" ] || {
                jl_error "Missing metadata field 'last_modified_at' in $file"
                return "$JL_EXIT_VALIDATION"
            }
            ;;
        immutable)
            if jq -e '.metadata | has("last_modified_at")' "$file" >/dev/null; then
                jl_error "Immutable metadata must not contain last_modified_at: $file"
                return "$JL_EXIT_VALIDATION"
            fi
            ;;
        *)
            jl_error "Unknown metadata mutability: $mutability"
            return "$JL_EXIT_ARGUMENTS"
            ;;
    esac

    if jq -e '.metadata | has("created_by")' "$file" >/dev/null; then
        jl_error "v1.1 metadata must not contain created_by: $file"
        return "$JL_EXIT_VALIDATION"
    fi
}
