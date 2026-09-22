#!/usr/bin/env bash
# Canonical machine-facing dispatcher for the JL Mixing Automation API.
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="${JL_MIXING_HOME:-$(cd "$SCRIPT_DIR/.." && pwd)}"
# shellcheck source=lib/metadata.sh
. "$APP_ROOT/lib/metadata.sh"
# shellcheck source=lib/client-create.sh
. "$APP_ROOT/lib/client-create.sh"

usage() {
    cat <<'USAGE'
Usage:
  jl-mixing system-info --json
  jl-mixing client create CLIENT_ID --json [options]
  jl-mixing --help

Commands:
  system-info --json  Print Automation API discovery information.
  client create        Create or preview a client and return one API response.

Client create options:
  --name NAME
  --artist NAME
  --sample-rate HZ
  --bit-depth BITS
  --file-format FORMAT
  --delivery-method TEXT
  --deliverables LIST
  --dry-run
USAGE
}

read_api_version() {
    local version_file version
    version_file="${JL_MIXING_API_VERSION_FILE:-$APP_ROOT/API_VERSION}"
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

require_python() {
    local python
    python="${JL_MIXING_PYTHON:-$(command -v python3 || true)}"
    [ -n "$python" ] && [ -x "$python" ] || {
        jl_error "Python 3 is required to produce Automation API JSON."
        return "$JL_EXIT_CONFIG"
    }
    printf '%s\n' "$python"
}

system_info() {
    local api_version application_version schema_dir python
    [ "$#" -eq 1 ] && [ "$1" = "--json" ] || {
        jl_error "system-info requires exactly --json."
        return "$JL_EXIT_ARGUMENTS"
    }

    api_version="$(read_api_version)" || return $?
    application_version="$(jl_software_version)" || return $?
    schema_dir="$APP_ROOT/api/schemas/v$api_version"
    if [ ! -d "$schema_dir" ]; then
        jl_error "Installed Automation API schemas are missing: $schema_dir"
        return "$JL_EXIT_CONFIG"
    fi
    schema_dir="$(cd "$schema_dir" && pwd -P)"
    python="$(require_python)" || return $?

    "$python" - "$api_version" "$application_version" "$schema_dir" <<'PY_SYSTEM_INFO'
import json
import sys
api_version, application_version, schema_dir = sys.argv[1:]
document = {
    "api_version": api_version,
    "application": {"name": "jl-mixing", "version": application_version},
    "metadata": {
        "readable_schema_versions": ["1.1.0"],
        "writable_schema_version": "1.1.0",
    },
    "capabilities": ["client.create", "system.info"],
    "schemas": {
        "installed_path": schema_dir,
        "public_base_url": f"https://jlaudio.github.io/jl-mixing/api/v{api_version}/schemas/",
    },
}
print(json.dumps(document, separators=(",", ":"), sort_keys=True))
PY_SYSTEM_INFO
}

client_create_response() {
    local api_version python json_seen dry_run client_id arg output_file error_file status
    local client_path workspace_path error_code response_status
    api_version="$(read_api_version)" || return $?
    python="$(require_python)" || return $?
    json_seen=0
    dry_run=0
    client_id=""

    [ "$#" -gt 0 ] || {
        jl_error "client create requires CLIENT_ID and --json."
        return "$JL_EXIT_ARGUMENTS"
    }
    client_id="$1"
    shift
    set -- "$client_id" "$@"

    for arg in "$@"; do
        case "$arg" in
            --json) json_seen=$((json_seen + 1)) ;;
            --dry-run) dry_run=1 ;;
            --cd|--no-cd)
                jl_error "client create JSON mode does not accept --cd or --no-cd."
                return "$JL_EXIT_ARGUMENTS"
                ;;
        esac
    done
    [ "$json_seen" -eq 1 ] || {
        jl_error "client create requires exactly one --json option."
        return "$JL_EXIT_ARGUMENTS"
    }

    # Remove the dispatcher-only --json flag before invoking the shared service.
    # Positional and option ordering is preserved.
    output_file="$(mktemp "${TMPDIR:-/tmp}/jl-mixing-client-out.XXXXXX")"
    error_file="$(mktemp "${TMPDIR:-/tmp}/jl-mixing-client-err.XXXXXX")"
    cleanup_client_api() { rm -f -- "$output_file" "$error_file"; }
    trap cleanup_client_api EXIT HUP INT TERM
    filtered_args=()
    for arg in "$@"; do
        [ "$arg" = "--json" ] || filtered_args+=("$arg")
    done

    set +e
    (jl_client_create_command "${filtered_args[@]}") >"$output_file" 2>"$error_file"
    status=$?
    set -e

    client_path="$(sed -n 's/^Client folder:[[:space:]]*//p' "$output_file" | head -1)"
    workspace_path=""
    if [ -n "$client_path" ]; then
        workspace_path="$(dirname "$(dirname "$client_path")")"
    fi

    if [ "$status" -eq 0 ]; then
        if [ "$dry_run" -eq 1 ]; then response_status=planned; else response_status=success; fi
        "$python" - "$api_version" "$response_status" "$client_id" "$client_path" "$workspace_path" "$dry_run" <<'PY_SUCCESS'
import json, sys
api_version, status, client_id, client_path, workspace_path, dry_run = sys.argv[1:]
data = {
    "client": {"id": client_id, "path": client_path},
    "configuration_path": f"{client_path}/client.json",
    "workspace_path": workspace_path,
}
if dry_run == "1":
    data["would_create"] = [f"{client_path}/client.json", f"{client_path}/Projects"]
doc = {"api_version": api_version, "operation": "client.create", "status": status,
       "data": data, "warnings": [], "errors": []}
print(json.dumps(doc, separators=(",", ":"), sort_keys=True))
PY_SUCCESS
        trap - EXIT HUP INT TERM
        cleanup_client_api
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
        error_code=CLIENT_ALREADY_EXISTS
    fi
    "$python" - "$api_version" "$response_status" "$error_code" "$status" "$error_file" <<'PY_ERROR'
import json, sys
from pathlib import Path
api_version, status, code, exit_code, error_path = sys.argv[1:]
message = Path(error_path).read_text(encoding="utf-8").strip() or "Client creation failed."
doc = {"api_version": api_version, "operation": "client.create", "status": status,
       "data": {}, "warnings": [], "errors": [{"code": code, "message": message,
       "details": {"exit_code": int(exit_code)}, "retryable": False}]}
print(json.dumps(doc, separators=(",", ":"), sort_keys=True))
PY_ERROR
    trap - EXIT HUP INT TERM
    cleanup_client_api
    return "$status"
}

[ "$#" -gt 0 ] || { usage >&2; exit "$JL_EXIT_ARGUMENTS"; }
case "$1" in
    -h|--help)
        [ "$#" -eq 1 ] || { jl_error "--help does not accept additional arguments."; exit "$JL_EXIT_ARGUMENTS"; }
        usage
        ;;
    system-info)
        shift
        system_info "$@"
        ;;
    client)
        shift
        [ "$#" -gt 0 ] && [ "$1" = create ] || { jl_error "Unknown client operation."; exit "$JL_EXIT_ARGUMENTS"; }
        shift
        client_create_response "$@"
        ;;
    *)
        jl_error "Unknown Automation API command: $1"
        usage >&2
        exit "$JL_EXIT_ARGUMENTS"
        ;;
esac
