#!/usr/bin/env bash
# Current client, project, studio, and revision detection.
#
# Context is discovered by walking upward from a starting path. Explicit paths
# always override discovery and are validated before being returned.
if [ "${JL_MIXING_CONTEXT_LOADED:-0}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi
JL_MIXING_CONTEXT_LOADED=1

JL_CONTEXT_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$JL_CONTEXT_LIB_DIR/common.sh"
# shellcheck source=lib/platform.sh
. "$JL_CONTEXT_LIB_DIR/platform.sh"
# shellcheck source=lib/json.sh
. "$JL_CONTEXT_LIB_DIR/json.sh"
# shellcheck source=lib/config.sh
. "$JL_CONTEXT_LIB_DIR/config.sh"
# shellcheck source=lib/naming.sh
. "$JL_CONTEXT_LIB_DIR/naming.sh"
# shellcheck source=lib/project-state.sh
. "$JL_CONTEXT_LIB_DIR/project-state.sh"

# Walk from a starting path toward / until a relative marker is found.
jl_find_up() {
    local start_path relative_marker current parent
    start_path="$1"
    relative_marker="$2"
    current="$(jl_abspath_allow_missing "$start_path")" || return $?
    [ -d "$current" ] || current="$(dirname "$current")"

    while :; do
        if [ -e "$current/$relative_marker" ]; then
            printf '%s\n' "$current"
            return 0
        fi
        parent="$(dirname "$current")"
        [ "$parent" != "$current" ] || break
        current="$parent"
    done
    return "$JL_EXIT_CONTEXT"
}

# Find the enclosing project by its 00_Admin manifest.
jl_context_project_root() {
    local start_path
    start_path="${1:-$PWD}"
    jl_find_up "$start_path" '00_Admin/project-manifest.json'
}

# Find the enclosing client by client.json.
jl_context_client_root() {
    local start_path
    start_path="${1:-$PWD}"
    jl_find_up "$start_path" 'client.json'
}

# Find the enclosing or configured studio workspace.
jl_context_studio_root() {
    local start_path
    start_path="${1:-$PWD}"
    jl_config_find_root "$start_path"
}

# Validate an explicit project reference or discover project context.
jl_context_resolve_project() {
    local explicit_path start_path candidate
    explicit_path="${1:-}"
    start_path="${2:-$PWD}"

    if [ -n "$explicit_path" ]; then
        candidate="$(jl_abspath_allow_missing "$explicit_path")" || return $?
        if [ -f "$candidate" ] && [ "$(basename "$candidate")" = 'project-manifest.json' ]; then
            candidate="$(cd "$(dirname "$candidate")/.." && pwd)"
        fi
        if [ -f "$candidate/00_Admin/project-manifest.json" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
        jl_error "Project not found at explicit path: $explicit_path"
        return "$JL_EXIT_CONTEXT"
    fi

    jl_context_project_root "$start_path" || {
        jl_error "No project context found from: $start_path"
        return "$JL_EXIT_CONTEXT"
    }
}

# Validate an explicit client reference or discover client context.
jl_context_resolve_client() {
    local explicit_path start_path candidate
    explicit_path="${1:-}"
    start_path="${2:-$PWD}"

    if [ -n "$explicit_path" ]; then
        candidate="$(jl_abspath_allow_missing "$explicit_path")" || return $?
        if [ -f "$candidate" ] && [ "$(basename "$candidate")" = 'client.json' ]; then
            candidate="$(dirname "$candidate")"
        fi
        if [ -f "$candidate/client.json" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
        jl_error "Client not found at explicit path: $explicit_path"
        return "$JL_EXIT_CONTEXT"
    fi

    jl_context_client_root "$start_path" || {
        jl_error "No client context found from: $start_path"
        return "$JL_EXIT_CONTEXT"
    }
}

# Return the manifest path for a resolved project root.
jl_context_project_manifest() {
    local project_root
    project_root="$1"
    printf '%s/00_Admin/project-manifest.json\n' "${project_root%/}"
}

# Read the project current_revision value.
jl_context_current_revision_number() {
    local project_root manifest
    project_root="$1"
    manifest="$(jl_context_project_manifest "$project_root")"
    jl_json_get "$manifest" '.state.current_revision'
}

# Resolve the folder for the current revision record.
jl_context_current_revision_root() {
    local project_root revision_number revision_folder
    project_root="$1"
    revision_number="$(jl_context_current_revision_number "$project_root")" || return $?
    if [ "$revision_number" -lt 1 ]; then
        jl_error "The project does not have a current revision."
        return "$JL_EXIT_CONTEXT"
    fi

    revision_folder="$(jl_json_get "$project_root/00_Admin/project-manifest.json" \
        ".revisions[] | select(.number == $revision_number) | .folder")" || return $?
    printf '%s/%s\n' "${project_root%/}" "$revision_folder"
}

# Resolve a client reference that may be a path, client.json file, or client ID.
# Locate a client by stable client_id, path, or exact directory name.
jl_context_find_client() {
    local studio_root reference candidate matches match_count
    studio_root="$1"
    reference="$2"

    if [ -z "$reference" ]; then
        jl_context_resolve_client "" "$PWD"
        return $?
    fi

    candidate="$(jl_abspath_allow_missing "$reference")" || return $?
    if [ -f "$candidate" ] && [ "$(basename "$candidate")" = client.json ]; then
        candidate="$(dirname "$candidate")"
    fi
    if [ -f "$candidate/client.json" ]; then
        printf '%s\n' "$candidate"
        return 0
    fi

    matches="$(find "$studio_root/Clients" -mindepth 2 -maxdepth 2 -name client.json -type f -print 2>/dev/null |
        while IFS= read -r client_file; do
            if [ "$(jl_json_get_optional "$client_file" '.client_id' '')" = "$reference" ]; then
                dirname "$client_file"
            fi
            # Keep the loop status successful when this file is not a match.
            :
        done)"

    match_count="$(printf '%s\n' "$matches" | sed '/^$/d' | wc -l | tr -d ' ')"
    if [ "$match_count" = 1 ]; then
        printf '%s\n' "$matches"
        return 0
    fi
    if [ "$match_count" -gt 1 ]; then
        jl_error "Multiple clients use the ID '$reference'."
        return "$JL_EXIT_VALIDATION"
    fi

    jl_error "Client not found: $reference"
    return "$JL_EXIT_CONTEXT"
}

# Walk upward for a regular, non-symlink marker. v1.1 context discovery uses
# this stricter form so a symlink cannot redirect a command across ownership or
# workspace boundaries.
jl_find_up_safe() {
    local start_path relative_marker current parent marker
    start_path="$1"
    relative_marker="$2"
    current="$(jl_abspath_allow_missing "$start_path")" || return $?
    [ -d "$current" ] || current="$(dirname "$current")"

    while :; do
        marker="$current/$relative_marker"
        if [ -f "$marker" ] && [ ! -L "$marker" ]; then
            printf '%s\n' "$current"
            return 0
        fi
        parent="$(dirname "$current")"
        [ "$parent" != "$current" ] || break
        current="$parent"
    done
    return "$JL_EXIT_CONTEXT"
}

# Detect directory patterns that belong to the unsupported v1.0 workspace
# model. The schema remains authoritative; these checks improve diagnostics
# when legacy JSON is missing or damaged.
jl_context_reject_legacy_layout() {
    local studio_root legacy_path
    studio_root="$1"

    if [ -e "$studio_root/DAWs" ] || [ -L "$studio_root/DAWs" ]; then
        jl_error "Legacy v1.0 workspace layout detected: $studio_root/DAWs"
        jl_error "JL Mixing 1.1 requires a newly created workspace. No changes made."
        return "$JL_EXIT_VALIDATION"
    fi

    legacy_path="$(find "$studio_root/Clients" -type d \
        \( -path '*/Projects/Active' \
           -o -path '*/Projects/Completed' \
           -o -path '*/03_DAW_Project/Project' \
           -o -path '*/04_Revisions/Revision_*/Prints' \) \
        -print -quit 2>/dev/null || true)"
    if [ -n "$legacy_path" ]; then
        jl_error "Legacy v1.0 workspace layout detected: $legacy_path"
        jl_error "JL Mixing 1.1 requires a newly created workspace. No changes made."
        return "$JL_EXIT_VALIDATION"
    fi
}

# Require the exact v1.1 studio record and reject recognizable legacy layouts.
jl_context_require_v11_workspace() {
    local studio_root config_file actual_version
    studio_root="$1"
    config_file="$(jl_config_file "$studio_root")"

    [ -f "$config_file" ] && [ ! -L "$config_file" ] || {
        jl_error "Studio configuration not found or unsafe: $config_file"
        return "$JL_EXIT_CONFIG"
    }

    actual_version="$(jl_json_get_optional "$config_file" '.metadata.schema_version' '')"
    if [ "$actual_version" != 1.1.0 ]; then
        if [ -n "$actual_version" ]; then
            jl_error "This workspace uses JL Mixing schema version $actual_version."
        else
            jl_error "The studio schema version is missing or invalid: $config_file"
        fi
        jl_error "JL Mixing 1.1 requires a newly created workspace and does not migrate v1.0 workspaces."
        jl_error "No changes made."
        return "$JL_EXIT_VALIDATION"
    fi

    jl_json_require_exact_schema_identity "$config_file" mixing-studio 1.1.0 || return $?
    jl_json_require_created_with_semver "$config_file" || return $?
    jl_context_reject_legacy_layout "$studio_root"
}

# Find and validate the enclosing v1.1 studio workspace. When no marker is
# found upward, the configured default root is considered as the final fallback.
jl_context_studio_root_v11() {
    local start_path studio_root default_root
    start_path="${1:-$PWD}"

    if studio_root="$(jl_find_up_safe "$start_path" 'Studio/studio.json')"; then
        jl_context_require_v11_workspace "$studio_root" || return $?
        printf '%s\n' "$studio_root"
        return 0
    fi

    default_root="$(jl_abspath_allow_missing "$(jl_config_default_root)")" || return $?
    if [ -f "$default_root/Studio/studio.json" ] && [ ! -L "$default_root/Studio/studio.json" ]; then
        jl_context_require_v11_workspace "$default_root" || return $?
        printf '%s\n' "$default_root"
        return 0
    fi

    jl_error "No v1.1 studio context found from: $start_path"
    return "$JL_EXIT_CONTEXT"
}

# Find the enclosing v1.1 client through its client.json marker.
jl_context_client_root_v11() {
    local start_path client_root client_file
    start_path="${1:-$PWD}"
    client_root="$(jl_find_up_safe "$start_path" 'client.json')" || {
        jl_error "No v1.1 client context found from: $start_path"
        return "$JL_EXIT_CONTEXT"
    }
    client_file="$client_root/client.json"
    jl_json_require_exact_schema_identity "$client_file" mixing-client 1.1.0 || return $?
    printf '%s\n' "$client_root"
}

# Resolve an explicit v1.1 client path or use marker-based upward discovery.
jl_context_resolve_client_v11() {
    local explicit_path start_path candidate client_file
    explicit_path="${1:-}"
    start_path="${2:-$PWD}"

    if [ -z "$explicit_path" ]; then
        jl_context_client_root_v11 "$start_path"
        return $?
    fi

    candidate="$(jl_abspath_allow_missing "$explicit_path")" || return $?
    if [ -f "$candidate" ] && [ "$(basename "$candidate")" = client.json ]; then
        candidate="$(dirname "$candidate")"
    fi
    client_file="$candidate/client.json"
    if [ ! -f "$client_file" ] || [ -L "$client_file" ] || [ -L "$candidate" ]; then
        jl_error "Client not found or unsafe at explicit path: $explicit_path"
        return "$JL_EXIT_CONTEXT"
    fi
    jl_json_require_exact_schema_identity "$client_file" mixing-client 1.1.0 || return $?
    printf '%s\n' "$candidate"
}

# Find the enclosing v1.1 project through its governing manifest marker.
jl_context_project_root_v11() {
    local start_path project_root manifest
    start_path="${1:-$PWD}"
    project_root="$(jl_find_up_safe "$start_path" '00_Admin/project-manifest.json')" || {
        jl_error "No v1.1 project context found from: $start_path"
        return "$JL_EXIT_CONTEXT"
    }
    manifest="$project_root/00_Admin/project-manifest.json"
    jl_json_require_exact_schema_identity "$manifest" mixing-project 1.1.0 || return $?
    printf '%s\n' "$project_root"
}

# Resolve an explicit v1.1 project path or use marker-based upward discovery.
jl_context_resolve_project_v11() {
    local explicit_path start_path candidate manifest
    explicit_path="${1:-}"
    start_path="${2:-$PWD}"

    if [ -z "$explicit_path" ]; then
        jl_context_project_root_v11 "$start_path"
        return $?
    fi

    candidate="$(jl_abspath_allow_missing "$explicit_path")" || return $?
    if [ -f "$candidate" ] && [ "$(basename "$candidate")" = project-manifest.json ]; then
        candidate="$(dirname "$(dirname "$candidate")")"
    fi
    manifest="$candidate/00_Admin/project-manifest.json"
    if [ ! -f "$manifest" ] || [ -L "$manifest" ] || [ -L "$candidate" ]; then
        jl_error "Project not found or unsafe at explicit path: $explicit_path"
        return "$JL_EXIT_CONTEXT"
    fi
    jl_json_require_exact_schema_identity "$manifest" mixing-project 1.1.0 || return $?
    printf '%s\n' "$candidate"
}

# Resolve a numbered revision directory from the canonical flattened layout.
jl_context_revision_root_for_number() {
    local project_root number revision_name revision_root
    project_root="$1"
    number="$2"
    case "$number" in
        ''|*[!0-9]*|0) jl_error "Invalid revision number: $number"; return "$JL_EXIT_ARGUMENTS" ;;
    esac

    revision_name="$(jl_revision_name "$number")"
    revision_root="$project_root/04_Revisions/$revision_name"
    if [ ! -d "$revision_root" ] || [ -L "$revision_root" ]; then
        jl_error "Revision directory not found or unsafe: $revision_root"
        return "$JL_EXIT_CONTEXT"
    fi
    printf '%s\n' "$revision_root"
}

# Find the enclosing canonical Revision_NN boundary from any path inside it.
jl_context_revision_root_v11() {
    local start_path project_root current parent revisions_root name
    start_path="${1:-$PWD}"
    project_root="$(jl_context_project_root_v11 "$start_path")" || return $?
    revisions_root="$project_root/04_Revisions"
    current="$(jl_abspath_allow_missing "$start_path")" || return $?
    [ -d "$current" ] || current="$(dirname "$current")"

    while [ "$current" != "$project_root" ] && [ "$current" != / ]; do
        parent="$(dirname "$current")"
        if [ "$parent" = "$revisions_root" ]; then
            name="$(basename "$current")"
            if printf '%s\n' "$name" | grep -Eq '^Revision_[0-9]{2,}$'; then
                [ ! -L "$current" ] || {
                    jl_error "Revision boundary must not be a symbolic link: $current"
                    return "$JL_EXIT_UNSAFE"
                }
                printf '%s\n' "$current"
                return 0
            fi
        fi
        current="$parent"
    done

    jl_error "No revision context found from: $start_path"
    return "$JL_EXIT_CONTEXT"
}

# Return the canonical final-delivery boundary for a v1.1 project.
jl_context_delivery_root_v11() {
    local project_root delivery_root
    project_root="$1"
    delivery_root="$project_root/05_Final_Delivery"
    if [ ! -d "$delivery_root" ] || [ -L "$delivery_root" ]; then
        jl_error "Final-delivery directory not found or unsafe: $delivery_root"
        return "$JL_EXIT_CONTEXT"
    fi
    printf '%s\n' "$delivery_root"
}


# Validate the complete governing v1.1 context for a project before a workflow
# mutation. JSON Schema handles each document; this helper enforces identity
# relationships and project-state/filesystem invariants across the documents.
jl_context_validate_project_documents_v11() {
    local project_root manifest snapshot client_root client_file studio_root studio_file
    local studio_schema client_schema project_schema snapshot_schema
    local client_document_id client_id
    project_root="$1"
    manifest="$project_root/00_Admin/project-manifest.json"
    snapshot="$project_root/00_Admin/client-profile-snapshot.json"

    client_root="$(jl_context_client_root_v11 "$project_root")" || return $?
    client_file="$client_root/client.json"
    studio_root="$(jl_context_studio_root_v11 "$project_root")" || return $?
    studio_file="$studio_root/Studio/studio.json"

    studio_schema="$(jl_json_schema_path studio.schema.json)" || return $?
    client_schema="$(jl_json_schema_path client.schema.json)" || return $?
    project_schema="$(jl_json_schema_path project-manifest.schema.json)" || return $?
    snapshot_schema="$(jl_json_schema_path client-profile-snapshot.schema.json)" || return $?
    jl_json_validate_schema_pairs \
        "$studio_schema" "$studio_file" \
        "$client_schema" "$client_file" \
        "$project_schema" "$manifest" \
        "$snapshot_schema" "$snapshot" >/dev/null || return $?

    jl_json_require_exact_schema_identity "$studio_file" mixing-studio 1.1.0 || return $?
    jl_json_require_created_with_semver "$studio_file" || return $?
    jl_json_require_exact_schema_identity "$client_file" mixing-client 1.1.0 || return $?
    jl_json_require_created_with_semver "$client_file" || return $?
    jl_json_require_exact_schema_identity "$manifest" mixing-project 1.1.0 || return $?
    jl_json_require_created_with_semver "$manifest" || return $?
    jl_json_require_exact_schema_identity \
        "$snapshot" mixing-client-profile-snapshot 1.1.0 || return $?
    jl_json_require_created_with_semver "$snapshot" || return $?

    client_document_id="$(jl_json_get "$client_file" '.metadata.document_id')" || return $?
    client_id="$(jl_json_get "$client_file" '.client_id')" || return $?
    if [ "$(jl_json_get "$manifest" '.client.client_document_id')" != "$client_document_id" ] || \
       [ "$(jl_json_get "$manifest" '.client.client_id')" != "$client_id" ]; then
        jl_error "Project manifest client identity does not match the owning client."
        return "$JL_EXIT_VALIDATION"
    fi
    if [ "$(jl_json_get "$snapshot" '.source_client.client_document_id')" != "$client_document_id" ] || \
       [ "$(jl_json_get "$snapshot" '.source_client.client_id')" != "$client_id" ]; then
        jl_error "Client profile snapshot does not match the owning client."
        return "$JL_EXIT_VALIDATION"
    fi
}

jl_context_validate_project_v11() {
    local project_root studio_root
    project_root="$1"
    jl_context_validate_project_documents_v11 "$project_root" || return $?
    studio_root="$(jl_context_studio_root_v11 "$project_root")" || return $?
    jl_project_validate_state "$project_root" || return $?
    jl_json_validate_unique_uuids "$studio_root"
}

# Validate a project for an explicitly destructive delivery rebuild. This keeps
# every governing document, identity, revision record, pointer, and revision
# directory check, but deliberately ignores the current delivery package so
# --clean can replace a missing or malformed prior package.
jl_context_validate_project_v11_for_clean_delivery() {
    local project_root studio_root manifest
    project_root="$1"
    manifest="$project_root/00_Admin/project-manifest.json"
    jl_context_validate_project_documents_v11 "$project_root" || return $?
    studio_root="$(jl_context_studio_root_v11 "$project_root")" || return $?
    jl_project_validate_revision_records "$manifest" || return $?
    jl_project_validate_state_pointers "$manifest" || return $?
    jl_project_validate_revision_directories "$project_root" || return $?
    jl_json_validate_unique_uuids "$studio_root"
}
