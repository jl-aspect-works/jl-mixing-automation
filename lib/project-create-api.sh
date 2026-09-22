#!/usr/bin/env bash
# Structured Automation API adapter for the shared project-creation service.
set -eu

PROJECT_API_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_API_ROOT="${JL_MIXING_HOME:-$(cd "$PROJECT_API_DIR/.." && pwd)}"
# shellcheck source=lib/metadata.sh
. "$PROJECT_API_ROOT/lib/metadata.sh"
# shellcheck source=lib/project-create.sh
. "$PROJECT_API_ROOT/lib/project-create.sh"

jl_project_api_read_version() {
    local version_file version
    version_file="${JL_MIXING_API_VERSION_FILE:-$PROJECT_API_ROOT/API_VERSION}"
    if [ ! -f "$version_file" ]; then
        jl_error "API_VERSION file not found: $version_file"
        return "$JL_EXIT_CONFIG"
    fi
    version="$(sed -n '1p' "$version_file")"
    if ! printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+$'; then
        jl_error "Invalid Automation API version '$version' in: $version_file"
        return "$JL_EXIT_CONFIG"
    fi
    printf '%s\n' "$version"
}

jl_project_api_python() {
    local python
    python="${JL_MIXING_PYTHON:-$(command -v python3 || true)}"
    [ -n "$python" ] && [ -x "$python" ] || {
        jl_error "Python 3 is required to produce Automation API JSON."
        return "$JL_EXIT_CONFIG"
    }
    printf '%s\n' "$python"
}

jl_project_api_emit_preflight_error() {
    local api_version python code message exit_code
    api_version="$1"
    python="$2"
    code="$3"
    message="$4"
    exit_code="$5"
    "$python" - "$api_version" "$code" "$message" "$exit_code" <<'PY_ERROR'
import json, sys
api_version, code, message, exit_code = sys.argv[1:]
doc = {"api_version": api_version, "operation": "project.create", "status": "error",
       "data": {}, "warnings": [], "errors": [{"code": code, "message": message,
       "details": {"exit_code": int(exit_code)}, "retryable": False}]}
print(json.dumps(doc, separators=(",", ":"), sort_keys=True))
PY_ERROR
}

jl_project_create_response() {
    local api_version python json_seen dry_run project_name arg output_file error_file status
    local project_path project_id artist initial_revision client_path client_id workspace_path
    local error_code response_status message previous
    api_version="$(jl_project_api_read_version)" || return $?
    python="$(jl_project_api_python)" || return $?
    json_seen=0
    dry_run=0
    project_name=""

    if [ "$#" -eq 0 ]; then
        jl_project_api_emit_preflight_error "$api_version" "$python" INVALID_REQUEST \
            "project create requires PROJECT_NAME and --json." "$JL_EXIT_ARGUMENTS"
        return "$JL_EXIT_ARGUMENTS"
    fi

    # Capture the display name from either supported new-mix form solely for
    # response metadata; the shared service remains authoritative for validation.
    if [ "${1#--}" = "$1" ]; then
        project_name="$1"
    fi
    previous=""
    for arg in "$@"; do
        if [ "$previous" = "--project" ]; then project_name="$arg"; fi
        case "$arg" in
            --json) json_seen=$((json_seen + 1)) ;;
            --dry-run) dry_run=1 ;;
            --cd|--no-cd)
                jl_project_api_emit_preflight_error "$api_version" "$python" INVALID_REQUEST \
                    "project create JSON mode does not accept --cd or --no-cd." "$JL_EXIT_ARGUMENTS"
                return "$JL_EXIT_ARGUMENTS"
                ;;
        esac
        previous="$arg"
    done
    if [ "$json_seen" -ne 1 ]; then
        jl_project_api_emit_preflight_error "$api_version" "$python" INVALID_REQUEST \
            "project create requires exactly one --json option." "$JL_EXIT_ARGUMENTS"
        return "$JL_EXIT_ARGUMENTS"
    fi

    output_file="$(mktemp "${TMPDIR:-/tmp}/jl-mixing-project-out.XXXXXX")"
    error_file="$(mktemp "${TMPDIR:-/tmp}/jl-mixing-project-err.XXXXXX")"
    cleanup_project_api() { rm -f -- "$output_file" "$error_file"; }
    trap cleanup_project_api EXIT HUP INT TERM

    filtered_args=()
    for arg in "$@"; do
        [ "$arg" = "--json" ] || filtered_args+=("$arg")
    done
    # Disable automatic directory changing for real machine-facing creates.
    # new-mix intentionally forbids --no-cd together with --dry-run.
    if [ "$dry_run" -eq 0 ]; then
        filtered_args+=(--no-cd)
    fi

    set +e
    (jl_project_create_command "${filtered_args[@]}") >"$output_file" 2>"$error_file"
    status=$?
    set -e

    project_path="$(sed -n 's/^Project folder:[[:space:]]*//p' "$output_file" | head -1)"
    project_id="$(sed -n 's/^Project ID:[[:space:]]*//p' "$output_file" | head -1)"
    artist="$(sed -n 's/^Artist:[[:space:]]*//p' "$output_file" | head -1)"
    initial_revision="$(sed -n 's/^Initial revision:[[:space:]]*//p' "$output_file" | head -1)"
    client_id="$(sed -n 's/^Client:.*(\([^()]\{1,\}\))[[:space:]]*$/\1/p' "$output_file" | head -1)"
    client_path=""
    workspace_path=""
    if [ -n "$project_path" ]; then
        client_path="$(dirname "$(dirname "$project_path")")"
        workspace_path="$(dirname "$(dirname "$client_path")")"
    fi

    if [ "$status" -eq 0 ]; then
        if [ "$dry_run" -eq 1 ]; then response_status=planned; else response_status=success; fi
        "$python" - "$api_version" "$response_status" "$project_name" "$project_id" "$artist" \
            "$project_path" "$initial_revision" "$client_id" "$client_path" "$workspace_path" "$dry_run" <<'PY_SUCCESS'
import json, sys
(api_version, status, project_name, project_id, artist, project_path, initial_revision,
 client_id, client_path, workspace_path, dry_run) = sys.argv[1:]
data = {
    "project": {"id": project_id, "name": project_name, "artist": artist, "path": project_path},
    "manifest_path": f"{project_path}/00_Admin/project-manifest.json",
    "client_snapshot_path": f"{project_path}/00_Admin/client-profile-snapshot.json",
    "initial_revision_path": initial_revision,
    "client": {"id": client_id, "path": client_path},
    "workspace_path": workspace_path,
}
if dry_run == "1":
    data["would_create"] = [
        f"{project_path}/00_Admin/project-manifest.json",
        f"{project_path}/00_Admin/client-profile-snapshot.json",
        initial_revision,
    ]
doc = {"api_version": api_version, "operation": "project.create", "status": status,
       "data": data, "warnings": [], "errors": []}
print(json.dumps(doc, separators=(",", ":"), sort_keys=True))
PY_SUCCESS
        trap - EXIT HUP INT TERM
        cleanup_project_api
        return 0
    fi

    case "$status" in
        2) error_code=INVALID_REQUEST; response_status=error ;;
        3) error_code=CONFIGURATION_ERROR; response_status=error ;;
        4) error_code=WORKSPACE_CONTEXT_ERROR; response_status=error ;;
        5) error_code=VALIDATION_FAILED; response_status=blocked ;;
        6) error_code=UNSAFE_OPERATION; response_status=blocked ;;
        *) error_code=INTERNAL_ERROR; response_status=error ;;
    esac
    if grep -Eqi 'already exists|already in use|already assigned|collision' "$error_file"; then
        error_code=PROJECT_ALREADY_EXISTS
    elif grep -Eqi 'client not found|client.*required|studio context.*required' "$error_file"; then
        error_code=CLIENT_NOT_FOUND
    fi
    message="$(cat "$error_file")"
    [ -n "$message" ] || message="Project creation failed."
    "$python" - "$api_version" "$response_status" "$error_code" "$status" "$message" <<'PY_SERVICE_ERROR'
import json, sys
api_version, status, code, exit_code, message = sys.argv[1:]
doc = {"api_version": api_version, "operation": "project.create", "status": status,
       "data": {}, "warnings": [], "errors": [{"code": code, "message": message.strip(),
       "details": {"exit_code": int(exit_code)}, "retryable": False}]}
print(json.dumps(doc, separators=(",", ":"), sort_keys=True))
PY_SERVICE_ERROR
    trap - EXIT HUP INT TERM
    cleanup_project_api
    return "$status"
}
