#!/usr/bin/env bash
# Structured Automation API adapter for revision approval.
set -eu

APPROVAL_API_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPROVAL_API_ROOT="${JL_MIXING_HOME:-$(cd "$APPROVAL_API_DIR/.." && pwd)}"
# shellcheck source=lib/metadata.sh
. "$APPROVAL_API_ROOT/lib/metadata.sh"
# shellcheck source=lib/revision-approve.sh
. "$APPROVAL_API_ROOT/lib/revision-approve.sh"

jl_approval_api_read_version() {
    local f v
    f="${JL_MIXING_API_VERSION_FILE:-$APPROVAL_API_ROOT/API_VERSION}"
    [ -f "$f" ] || { jl_error "API_VERSION file not found: $f"; return "$JL_EXIT_CONFIG"; }
    v="$(sed -n '1p' "$f")"
    printf '%s\n' "$v" | grep -Eq '^[0-9]+\.[0-9]+$' || { jl_error "Invalid Automation API version '$v' in: $f"; return "$JL_EXIT_CONFIG"; }
    printf '%s\n' "$v"
}

jl_approval_api_python() {
    local p
    p="${JL_MIXING_PYTHON:-$(command -v python3 || true)}"
    [ -n "$p" ] && [ -x "$p" ] || { jl_error "Python 3 is required to produce Automation API JSON."; return "$JL_EXIT_CONFIG"; }
    printf '%s\n' "$p"
}

jl_approval_api_emit_error() {
    local api python status code message exit_code
    api="$1"; python="$2"; status="$3"; code="$4"; message="$5"; exit_code="$6"
    "$python" - "$api" "$status" "$code" "$message" "$exit_code" <<'PY'
import json,sys
api,status,code,message,exit_code=sys.argv[1:]
print(json.dumps({"api_version":api,"operation":"revision.approve","status":status,"data":{},"warnings":[],"errors":[{"code":code,"message":message,"details":{"exit_code":int(exit_code)},"retryable":False}]},separators=(",",":"),sort_keys=True))
PY
}

jl_revision_approve_response() {
    local api python json_seen project_ref project_seen dry_run previous arg
    local out err rc project_path manifest workspace project_id revision_number revision_path
    local approved_by approved_at response_status code message
    api="$(jl_approval_api_read_version)" || return $?
    python="$(jl_approval_api_python)" || return $?
    json_seen=0; project_ref=""; project_seen=0; dry_run=0; previous=""
    for arg in "$@"; do
        if [ "$previous" = "--project" ]; then project_ref="$arg"; project_seen=$((project_seen+1)); fi
        case "$arg" in --json) json_seen=$((json_seen+1));; --dry-run) dry_run=1;; esac
        previous="$arg"
    done
    if [ "$json_seen" -ne 1 ]; then
        jl_approval_api_emit_error "$api" "$python" error INVALID_REQUEST "revision approve requires exactly one --json option." "$JL_EXIT_ARGUMENTS"
        return "$JL_EXIT_ARGUMENTS"
    fi
    if [ "$project_seen" -ne 1 ] || [ -z "$project_ref" ]; then
        jl_approval_api_emit_error "$api" "$python" error INVALID_REQUEST "revision approve JSON mode requires exactly one --project PATH option." "$JL_EXIT_ARGUMENTS"
        return "$JL_EXIT_ARGUMENTS"
    fi
    project_path="$($python - "$PWD" "$project_ref" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[2]).expanduser()
if not p.is_absolute(): p=Path(sys.argv[1])/p
print(p.resolve(strict=False))
PY
)"
    manifest="$project_path/00_Admin/project-manifest.json"
    workspace="$(dirname "$(dirname "$(dirname "$(dirname "$project_path")")")")"
    out="$(mktemp "${TMPDIR:-/tmp}/jl-mixing-approve-out.XXXXXX")"
    err="$(mktemp "${TMPDIR:-/tmp}/jl-mixing-approve-err.XXXXXX")"
    cleanup_approval_api(){ rm -f -- "$out" "$err"; }
    trap cleanup_approval_api EXIT HUP INT TERM
    filtered_args=(); for arg in "$@"; do [ "$arg" = "--json" ] || filtered_args+=("$arg"); done
    set +e
    (jl_revision_approve_command "${filtered_args[@]}") >"$out" 2>"$err"
    rc=$?
    set -e

    revision_number="$(sed -n -e 's/^Approved revision:[[:space:]]*//p' -e 's/^Selected revision:[[:space:]]*//p' "$out" | head -1)"
    approved_by="$(sed -n -e 's/^Approved by:[[:space:]]*//p' -e 's/^Approver:[[:space:]]*//p' "$out" | head -1)"
    approved_at="$(sed -n 's/^Approved at:[[:space:]]*//p' "$out" | head -1)"

    if [ "$rc" -eq 0 ] && [ -n "$revision_number" ]; then
        project_id=""
        if [ -f "$manifest" ]; then
            project_id="$($python - "$manifest" <<'PY'
import json,sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text()).get("project_id",""))
PY
)"
        fi
        revision_path="$(printf '%s/04_Revisions/Revision_%02d' "$project_path" "$revision_number")"
        if [ "$dry_run" -eq 1 ]; then response_status=planned; else response_status=success; fi
        "$python" - "$api" "$response_status" "$project_id" "$project_path" "$manifest" "$workspace" "$revision_number" "$revision_path" "$approved_by" "$approved_at" "$dry_run" <<'PY'
import json,sys
api,status,project_id,project_path,manifest,workspace,number,revision_path,approved_by,approved_at,dry_run=sys.argv[1:]
data={"project":{"id":project_id,"path":project_path},"manifest_path":manifest,"workspace_path":workspace,"revision":{"number":int(number),"path":revision_path},"approved_by":approved_by,"approved_at":approved_at or None}
if dry_run=="1": data["would_update"]=[manifest]
print(json.dumps({"api_version":api,"operation":"revision.approve","status":status,"data":data,"warnings":[],"errors":[]},separators=(",",":"),sort_keys=True))
PY
        trap - EXIT HUP INT TERM; cleanup_approval_api; return 0
    fi

    case "$rc" in 2) code=INVALID_REQUEST; response_status=error;; 3) code=CONFIGURATION_ERROR; response_status=error;; 4) code=WORKSPACE_CONTEXT_ERROR; response_status=error;; 5) code=VALIDATION_FAILED; response_status=blocked;; 6) code=UNSAFE_OPERATION; response_status=blocked;; *) code=INTERNAL_ERROR; response_status=error;; esac
    if grep -Eqi 'already the approved revision' "$err"; then code=REVISION_ALREADY_APPROVED
    elif grep -Eqi 'Revision [0-9]+ does not exist|No revision exists' "$err"; then code=REVISION_NOT_FOUND
    elif grep -Eqi 'approval timestamp|timestamp predates' "$err"; then code=INVALID_APPROVAL_TIMESTAMP
    elif grep -Eqi 'project.*not found|resolve project|project context' "$err"; then code=PROJECT_NOT_FOUND
    fi
    message="$(cat "$err")"; [ -n "$message" ] || message="Revision approval failed."
    jl_approval_api_emit_error "$api" "$python" "$response_status" "$code" "$message" "$rc"
    trap - EXIT HUP INT TERM; cleanup_approval_api; return "$rc"
}
