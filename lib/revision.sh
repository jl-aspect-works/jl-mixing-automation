#!/usr/bin/env bash
# Revision numbering and v1.1 project-manifest state transitions.
#
# Revision status is derived from the three project state pointers. The manifest
# stores immutable revision identity/creation data plus mutable approval fields;
# it does not store status labels or directory paths.
if [ "${JL_MIXING_REVISION_LOADED:-0}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi
JL_MIXING_REVISION_LOADED=1

JL_REVISION_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$JL_REVISION_LIB_DIR/common.sh"
# shellcheck source=lib/json.sh
. "$JL_REVISION_LIB_DIR/json.sh"
# shellcheck source=lib/metadata.sh
. "$JL_REVISION_LIB_DIR/metadata.sh"

# Return state.current_revision + 1 for an exact v1.1 project document.
# Command callers validate all cross-record invariants before using this value.
jl_revision_next_number() {
    local manifest current
    manifest="$1"
    jl_json_require_exact_schema_identity "$manifest" mixing-project 1.1.0 || return $?
    current="$(jl_json_get "$manifest" '.state.current_revision')" || return $?
    case "$current" in
        ''|*[!0-9]*)
            jl_error "Invalid state.current_revision in: $manifest"
            return "$JL_EXIT_VALIDATION"
            ;;
    esac
    printf '%s\n' "$((current + 1))"
}

# Build one canonical v1.1 revision record as JSON.
jl_revision_create_record() {
    local number description revision_id timestamp
    number="$1"
    description="$2"
    revision_id="${3:-$(jl_uuid)}"
    timestamp="${4:-$(jl_now_iso8601)}"

    case "$number" in
        ''|*[!0-9]*|0)
            jl_error "Revision number must be a positive integer: $number"
            return "$JL_EXIT_ARGUMENTS"
            ;;
    esac
    [ -n "$(jl_trim "$description")" ] || {
        jl_error "Revision description must not be empty."
        return "$JL_EXIT_VALIDATION"
    }

    jq -n \
        --argjson number "$number" \
        --arg revision_id "$revision_id" \
        --arg created_at "$timestamp" \
        --arg description "$description" \
        '{
            number: $number,
            revision_id: $revision_id,
            created_at: $created_at,
            description: $description,
            approval: {
                approved_at: null,
                approved_by: null
            }
        }'
}

# Append one canonical revision record and advance current_revision. Approval
# and delivery pointers are deliberately preserved when new work begins.
jl_revision_append() {
    local manifest description number timestamp revision_id record
    manifest="$1"
    description="$2"
    number="${3:-$(jl_revision_next_number "$manifest")}"
    timestamp="${4:-$(jl_now_iso8601)}"
    revision_id="${5:-$(jl_uuid)}"
    record="$(jl_revision_create_record \
        "$number" "$description" "$revision_id" "$timestamp")" || return $?

    jl_json_update "$manifest" \
        '.revisions += [$revision] |
         .state.current_revision = $number |
         .metadata.last_modified_at = $timestamp' \
        --argjson revision "$record" \
        --argjson number "$number" \
        --arg timestamp "$timestamp"
}

# Record approval for one revision and move only approved_revision. Historical
# approval metadata on every other revision is retained unchanged.
jl_revision_approve() {
    local manifest number approved_by timestamp exists current_approved
    manifest="$1"
    number="$2"
    approved_by="$3"
    timestamp="${4:-$(jl_now_iso8601)}"

    jl_json_require_exact_schema_identity "$manifest" mixing-project 1.1.0 || return $?
    case "$number" in
        ''|*[!0-9]*|0)
            jl_error "Revision number must be a positive integer: $number"
            return "$JL_EXIT_ARGUMENTS"
            ;;
    esac
    [ -n "$(jl_trim "$approved_by")" ] || {
        jl_error "Approver must not be empty."
        return "$JL_EXIT_VALIDATION"
    }

    exists="$(jq --argjson number "$number" \
        '[.revisions[] | select(.number == $number)] | length' "$manifest")" || return $?
    if [ "$exists" -ne 1 ]; then
        jl_error "Revision $number does not exist exactly once."
        return "$JL_EXIT_VALIDATION"
    fi

    current_approved="$(jl_json_get_optional "$manifest" '.state.approved_revision' '')"
    if [ -n "$current_approved" ] && [ "$current_approved" -eq "$number" ]; then
        jl_error "Revision $number is already the approved revision."
        return "$JL_EXIT_VALIDATION"
    fi

    jl_json_update "$manifest" \
        '.revisions |= map(
            if .number == $number then
                .approval.approved_at = $timestamp |
                .approval.approved_by = $approved_by
            else . end
         ) |
         .state.approved_revision = $number |
         .metadata.last_modified_at = $timestamp' \
        --argjson number "$number" \
        --arg timestamp "$timestamp" \
        --arg approved_by "$approved_by"
}

# Return a derived v1.1 revision status from the project pointers.
jl_revision_status() {
    local manifest number current approved exists
    manifest="$1"
    number="$2"

    jl_json_require_exact_schema_identity "$manifest" mixing-project 1.1.0 || return $?
    exists="$(jq --argjson number "$number" \
        '[.revisions[] | select(.number == $number)] | length' "$manifest")" || return $?
    [ "$exists" -eq 1 ] || {
        jl_error "Revision $number does not exist exactly once."
        return "$JL_EXIT_VALIDATION"
    }
    current="$(jl_json_get "$manifest" '.state.current_revision')" || return $?
    approved="$(jl_json_get_optional "$manifest" '.state.approved_revision' '')"
    if [ -n "$approved" ] && [ "$number" -eq "$approved" ]; then
        printf '%s\n' approved
    elif [ "$number" -eq "$current" ]; then
        printf '%s\n' open
    else
        printf '%s\n' superseded
    fi
}

# Read the current revision number from project state.
jl_revision_current() {
    local manifest
    manifest="$1"
    jl_json_get "$manifest" '.state.current_revision'
}
