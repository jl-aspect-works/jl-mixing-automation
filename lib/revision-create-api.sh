#!/usr/bin/env bash
# Structured Automation API adapter for the shared revision-creation service.
set -eu

REVISION_API_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REVISION_API_ROOT="${JL_MIXING_HOME:-$(cd "$REVISION_API_DIR/.." && pwd)}"
# shellcheck source=lib/metadata.sh
. "$REVISION_API_ROOT/lib/metadata.sh"
# shellcheck source=lib/revision-create.sh
. "$REVISION_API_ROOT/lib/revision-create.sh"

jl_revision_api_read_version() {
    local version_file version
    version_file="${JL_MIXING_API_VERSION_FILE:-$REVISION_API_ROOT/API_VERSION}"
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

jl_revision_api_python() {
    local python
    python="${JL_MIXING_PYTHON:-$(command -v python3 || true)}"
    [ -n "$python" ] && [ -x "$python" ] || {
        jl_error "Python 3 is required to produce Automation API JSON."
        return "$JL_EXIT_CONFIG"
    }
    printf '%s\n' "$python"
}

jl_revision_api_emit_preflight_error() {
    local api_version python code message exit_code
    api_version="$1"
    python="$2"
    code="$3"
    message="$4"
    exit_code="$5"
    "$python" - "$api_version" "$code" "$message" "$exit_code" <<'PY_ERROR'
import json, sys
api_version, code, message, exit_code = sys.argv[1:]
doc = {"api_version": api_version, "operation": "revision.create", "status": "error",
       "data": {}, "warnings": [], "errors": [{"code": code, "message": message,
       "details": {"exit_code": int(exit_code)}, "retryable": False}]}
print(json.dumps(doc, separators=(",", ":"), sort_keys=True))
PY_ERROR
}

jl_revision_create_response() {
    local api_version python json_seen dry_run arg output_file error_file status
    local revision_path revision_number revision_description project_path manifest_path workspace_path project_id
    local error_code response_status message
    api_version="$(jl_revision_api_read_version)" || return $?
    python="$(jl_revision_api_python)" || return $?
    json_seen=0
    dry_run=0

    for arg in "$@"; do
        case "$arg" in
            --json) json_seen=$((json_seen + 1)) ;;
            --dry-run) dry_run=1 ;;
            --cd|--no-cd)
                jl_revision_api_emit_preflight_error "$api_version" "$python" INVALID_REQUEST \
                    "revision create JSON mode does not accept --cd or --no-cd." "$JL_EXIT_ARGUMENTS"
                return "$JL_EXIT_ARGUMENTS"
                ;;
        esac
    done
    if [ "$json_seen" -ne 1 ]; then
        jl_revision_api_emit_preflight_error "$api_version" "$python" INVALID_REQUEST \
            "revision create requires exactly one --json option." "$JL_EXIT_ARGUMENTS"
        return "$JL_EXIT_ARGUMENTS"
    fi

    output_file="$(mktemp "${TMPDIR:-/tmp}/jl-mixing-revision-out.XXXXXX")"
    error_file="$(mktemp "${TMPDIR:-/tmp}/jl-mixing-revision-err.XXXXXX")"
    cleanup_revision_api() { rm -f -- "$output_file" "$error_file"; }
    trap cleanup_revision_api EXIT HUP INT TERM

    filtered_args=()
    for arg in "$@"; do
        [ "$arg" = "--json" ] || filtered_args+=("$arg")
    done
    # Machine calls never request shell directory integration. new-revision
    # rejects --no-cd with --dry-run, so suppress it for planning requests.
    if [ "$dry_run" -eq 0 ]; then
        filtered_args+=(--no-cd)
    fi

    set +e
    (jl_revision_create_command "${filtered_args[@]}") >"$output_file" 2>"$error_file"
    status=$?
    set -e

    revision_path="$(sed -n 's/^Revision folder:[[:space:]]*//p' "$output_file" | head -1)"
    revision_number="$(sed -n -e 's/^Revision:[[:space:]]*//p' -e 's/^New revision:[[:space:]]*//p' "$output_file" | head -1)"
    revision_description="$(sed -n 's/^Description:[[:space:]]*//p' "$output_file" | head -1)"
    project_path=""
    manifest_path=""
    workspace_path=""
    project_id=""
    if [ -n "$revision_path" ]; then
        project_path="$(dirname "$(dirname "$revision_path")")"
        manifest_path="$project_path/00_Admin/project-manifest.json"
        workspace_path="$(dirname "$(dirname "$(dirname "$(dirname "$project_path")")")")"
        if [ -f "$manifest_path" ]; then
            project_id="$("$python" - "$manifest_path" <<'PY_PROJECT_ID'
import json, sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("project_id", ""))
PY_PROJECT_ID
)"
        fi
    fi

    if [ "$status" -eq 0 ]; then
        if [ "$dry_run" -eq 1 ]; then response_status=planned; else response_status=success; fi
        "$python" - "$api_version" "$response_status" "$project_id" "$project_path" "$manifest_path" \
            "$revision_number" "$revision_path" "$revision_description" "$workspace_path" "$dry_run" <<'PY_SUCCESS'
import json, sys
(api_version, status, project_id, project_path, manifest_path,
 revision_number, revision_path, revision_description, workspace_path, dry_run) = sys.argv[1:]
data = {
    "project": {"id": project_id, "path": project_path},
    "manifest_path": manifest_path,
    "revision": {"number": int(revision_number), "path": revision_path, "description": revision_description},
    "revision_notes_path": f"{revision_path}/Revision_Notes.md",
    "workspace_path": workspace_path,
}
if dry_run == "1":
    data["would_create"] = [revision_path, f"{revision_path}/Revision_Notes.md"]
    data["would_update"] = [manifest_path]
doc = {"api_version": api_version, "operation": "revision.create", "status": status,
       "data": data, "warnings": [], "errors": []}
print(json.dumps(doc, separators=(",", ":"), sort_keys=True))
PY_SUCCESS
        trap - EXIT HUP INT TERM
        cleanup_revision_api
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
    if grep -Eqi 'already exists|collision' "$error_file"; then
        error_code=REVISION_ALREADY_EXISTS
    elif grep -Eqi 'source not found' "$error_file"; then
        error_code=SOURCE_NOT_FOUND
    fi
    message="$(cat "$error_file")"
    [ -n "$message" ] || message="Revision creation failed."
    "$python" - "$api_version" "$response_status" "$error_code" "$status" "$message" <<'PY_SERVICE_ERROR'
import json, sys
api_version, status, code, exit_code, message = sys.argv[1:]
doc = {"api_version": api_version, "operation": "revision.create", "status": status,
       "data": {}, "warnings": [], "errors": [{"code": code, "message": message.strip(),
       "details": {"exit_code": int(exit_code)}, "retryable": False}]}
print(json.dumps(doc, separators=(",", ":"), sort_keys=True))
PY_SERVICE_ERROR
    trap - EXIT HUP INT TERM
    cleanup_revision_api
    return "$status"
}
