#!/usr/bin/env bash
# Structured Automation API adapter for the shared intake-validation service.
set -eu

INTAKE_API_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTAKE_API_ROOT="${JL_MIXING_HOME:-$(cd "$INTAKE_API_DIR/.." && pwd)}"
# shellcheck source=lib/metadata.sh
. "$INTAKE_API_ROOT/lib/metadata.sh"
# shellcheck source=lib/intake-validate.sh
. "$INTAKE_API_ROOT/lib/intake-validate.sh"

jl_intake_api_read_version() {
    local version_file version
    version_file="${JL_MIXING_API_VERSION_FILE:-$INTAKE_API_ROOT/API_VERSION}"
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

jl_intake_api_python() {
    local python
    python="${JL_MIXING_PYTHON:-$(command -v python3 || true)}"
    [ -n "$python" ] && [ -x "$python" ] || {
        jl_error "Python 3 is required to produce Automation API JSON."
        return "$JL_EXIT_CONFIG"
    }
    printf '%s\n' "$python"
}

jl_intake_api_emit_error() {
    local api_version python status code message exit_code
    api_version="$1"; python="$2"; status="$3"; code="$4"; message="$5"; exit_code="$6"
    "$python" - "$api_version" "$status" "$code" "$message" "$exit_code" <<'PY_ERROR'
import json, sys
api_version, status, code, message, exit_code = sys.argv[1:]
doc = {"api_version": api_version, "operation": "intake.validate", "status": status,
       "data": {}, "warnings": [], "errors": [{"code": code, "message": message,
       "details": {"exit_code": int(exit_code)}, "retryable": False}]}
print(json.dumps(doc, separators=(",", ":"), sort_keys=True))
PY_ERROR
}

jl_intake_validate_response() {
    local api_version python json_seen dry_run project_ref project_seen arg previous
    local output_file error_file status project_path manifest_path report_path workspace_path project_id
    local files_discovered blocking_errors warning_count source_path ffprobe_available report_content_path
    local error_code response_status message completed_scan
    api_version="$(jl_intake_api_read_version)" || return $?
    python="$(jl_intake_api_python)" || return $?
    json_seen=0
    dry_run=0
    project_ref=""
    project_seen=0
    previous=""

    for arg in "$@"; do
        if [ "$previous" = "--project" ]; then
            project_ref="$arg"
            project_seen=$((project_seen + 1))
        fi
        case "$arg" in
            --json) json_seen=$((json_seen + 1)) ;;
            --dry-run) dry_run=1 ;;
            --progress=*)
                jl_intake_api_emit_error "$api_version" "$python" error INVALID_REQUEST \
                    "intake validate does not yet support JSON progress events." "$JL_EXIT_ARGUMENTS"
                return "$JL_EXIT_ARGUMENTS"
                ;;
        esac
        previous="$arg"
    done
    if [ "$json_seen" -ne 1 ]; then
        jl_intake_api_emit_error "$api_version" "$python" error INVALID_REQUEST \
            "intake validate requires exactly one --json option." "$JL_EXIT_ARGUMENTS"
        return "$JL_EXIT_ARGUMENTS"
    fi
    if [ "$project_seen" -ne 1 ] || [ -z "$project_ref" ]; then
        jl_intake_api_emit_error "$api_version" "$python" error INVALID_REQUEST \
            "intake validate JSON mode requires exactly one --project PATH option." "$JL_EXIT_ARGUMENTS"
        return "$JL_EXIT_ARGUMENTS"
    fi

    project_path="$($python - "$PWD" "$project_ref" <<'PY_PATH'
from pathlib import Path
import sys
base, value = sys.argv[1:]
p = Path(value).expanduser()
if not p.is_absolute():
    p = Path(base) / p
print(p.resolve(strict=False))
PY_PATH
)"
    manifest_path="$project_path/00_Admin/project-manifest.json"
    report_path="$project_path/00_Admin/Intake_Report.md"
    workspace_path="$(dirname "$(dirname "$(dirname "$(dirname "$project_path")")")")"

    output_file="$(mktemp "${TMPDIR:-/tmp}/jl-mixing-intake-out.XXXXXX")"
    error_file="$(mktemp "${TMPDIR:-/tmp}/jl-mixing-intake-err.XXXXXX")"
    cleanup_intake_api() { rm -f -- "$output_file" "$error_file"; }
    trap cleanup_intake_api EXIT HUP INT TERM

    filtered_args=()
    for arg in "$@"; do
        [ "$arg" = "--json" ] || filtered_args+=("$arg")
    done

    set +e
    (jl_intake_validate_command "${filtered_args[@]}") >"$output_file" 2>"$error_file"
    status=$?
    set -e

    # A completed scan always contains the Intake Summary fields, in either the
    # dry-run Markdown report or the normal human summary.
    files_discovered="$(sed -n -e 's/^- Files discovered:[[:space:]]*//p' -e 's/^Files inspected:[[:space:]]*//p' "$output_file" | head -1)"
    blocking_errors="$(sed -n -e 's/^- Blocking errors:[[:space:]]*//p' -e 's/^Blocking errors:[[:space:]]*//p' "$output_file" | head -1)"
    warning_count="$(sed -n -e 's/^- Warnings:[[:space:]]*//p' -e 's/^Warnings:[[:space:]]*//p' "$output_file" | head -1)"
    source_path="$(sed -n -e 's/^- Source: `\(.*\)`[[:space:]]*$/\1/p' -e 's/^Source:[[:space:]]*//p' "$output_file" | head -1)"
    completed_scan=0
    if [ -n "$files_discovered" ] && [ -n "$blocking_errors" ] && [ -n "$warning_count" ]; then
        completed_scan=1
    fi

    if [ "$completed_scan" -eq 1 ]; then
        project_id=""
        if [ -f "$manifest_path" ]; then
            project_id="$($python - "$manifest_path" <<'PY_PROJECT'
import json, sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("project_id", ""))
PY_PROJECT
)"
        fi
        if grep -q 'Enhanced inspection: available through ffprobe' "$output_file"; then
            ffprobe_available=true
        elif grep -q 'Enhanced inspection: unavailable' "$output_file"; then
            ffprobe_available=false
        else
            ffprobe_available=null
        fi
        if [ "$status" -eq 0 ]; then
            if [ "$dry_run" -eq 1 ]; then response_status=planned; else response_status=success; fi
        elif [ "$status" -eq "$JL_EXIT_VALIDATION" ]; then
            response_status=blocked
        else
            response_status=error
        fi
        if [ "$dry_run" -eq 1 ]; then
            report_content_path="$output_file"
        else
            report_content_path="$report_path"
        fi
        "$python" - "$api_version" "$response_status" "$project_id" "$project_path" "$manifest_path" \
            "$report_path" "$workspace_path" "$source_path" "$files_discovered" "$blocking_errors" \
            "$warning_count" "$ffprobe_available" "$dry_run" "$status" "$report_content_path" <<'PY_RESULT'
import json, sys
from pathlib import Path
(api_version, status, project_id, project_path, manifest_path, report_path,
 workspace_path, source_path, files_discovered, blocking_errors, warnings,
 ffprobe_available, dry_run, exit_code, report_content_path) = sys.argv[1:]
report_markdown = Path(report_content_path).read_text(encoding="utf-8")
data = {
    "project": {"id": project_id, "path": project_path},
    "manifest_path": manifest_path,
    "intake_report_path": report_path,
    "workspace_path": workspace_path,
    "source_path": source_path,
    "report_markdown": report_markdown,
    "summary": {
        "files_discovered": int(files_discovered),
        "blocking_errors": int(blocking_errors),
        "warnings": int(warnings),
        "ffprobe_available": None if ffprobe_available == "null" else ffprobe_available == "true",
    },
}
if dry_run == "1":
    data["would_update"] = [report_path]
errors = []
if status == "blocked":
    errors.append({"code": "INTAKE_BLOCKING_FINDINGS",
                   "message": "Intake validation completed with blocking findings.",
                   "details": {"exit_code": int(exit_code), "blocking_errors": int(blocking_errors)},
                   "retryable": False})
doc = {"api_version": api_version, "operation": "intake.validate", "status": status,
       "data": data, "warnings": [], "errors": errors}
print(json.dumps(doc, separators=(",", ":"), sort_keys=True))
PY_RESULT
        trap - EXIT HUP INT TERM
        cleanup_intake_api
        return "$status"
    fi

    case "$status" in
        2) error_code=INVALID_REQUEST; response_status=error ;;
        3) error_code=CONFIGURATION_ERROR; response_status=error ;;
        4) error_code=WORKSPACE_CONTEXT_ERROR; response_status=error ;;
        5) error_code=VALIDATION_FAILED; response_status=blocked ;;
        6) error_code=UNSAFE_OPERATION; response_status=blocked ;;
        *) error_code=INTERNAL_ERROR; response_status=error ;;
    esac
    if grep -Eqi 'source directory not found|source.*unsafe' "$error_file"; then
        error_code=SOURCE_NOT_FOUND
    elif grep -Eqi 'project.*not found|resolve project|project context' "$error_file"; then
        error_code=PROJECT_NOT_FOUND
    fi
    message="$(cat "$error_file")"
    [ -n "$message" ] || message="Intake validation failed."
    jl_intake_api_emit_error "$api_version" "$python" "$response_status" "$error_code" "$message" "$status"
    trap - EXIT HUP INT TERM
    cleanup_intake_api
    return "$status"
}
