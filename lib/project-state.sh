#!/usr/bin/env bash
# Derived v1.1 project state and cross-record/filesystem validation.
#
# The v1.1 manifest stores only three revision pointers. Revision status and the
# user-facing Setup/In progress/Approved/Delivered stage are calculated from
# those pointers plus the structurally valid final-delivery manifest.
if [ "${JL_MIXING_PROJECT_STATE_LOADED:-0}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi
JL_MIXING_PROJECT_STATE_LOADED=1

JL_PROJECT_STATE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JL_PROJECT_STATE_REPO_ROOT="$(cd "$JL_PROJECT_STATE_LIB_DIR/.." && pwd)"
# shellcheck source=lib/common.sh
. "$JL_PROJECT_STATE_LIB_DIR/common.sh"
# shellcheck source=lib/json.sh
. "$JL_PROJECT_STATE_LIB_DIR/json.sh"

# Run one state-validator mode and map its documented validation status to the
# shared JL Mixing exit-code contract.
jl_project_state_run_validator() {
    local mode path python_command status
    mode="$1"
    path="$2"
    python_command="$(jl_json_validator_python)" || {
        jl_error "Python 3 is required for project-state validation."
        return "$JL_EXIT_CONFIG"
    }

    if "$python_command" "$JL_PROJECT_STATE_REPO_ROOT/tools/project-state.py" "$mode" "$path"; then
        return 0
    else
        status=$?
    fi
    case "$status" in
        0) return 0 ;;
        5)
            jl_error "Invalid v1.1 project state: $path"
            return "$JL_EXIT_VALIDATION"
            ;;
        *)
            jl_error "Project-state validation could not be completed: $path"
            return "$JL_EXIT_GENERAL"
            ;;
    esac
}

# Validate contiguous revisions, current pointer correspondence,
# approval-field pairs, and approval timestamps.
jl_project_validate_revision_records() {
    jl_project_state_run_validator records "$1"
}

# Validate that approved and delivered pointers are null or identify existing,
# approved revision records.
jl_project_validate_state_pointers() {
    jl_project_state_run_validator pointers "$1"
}

# Validate exact Revision_NN directory correspondence without following
# symlinked revision boundaries.
jl_project_validate_revision_directories() {
    jl_project_state_run_validator directories "$1"
}

# Validate structural consistency between delivered_revision and the current
# authoritative delivery manifest. Hashes are not recalculated here.
jl_project_validate_delivery_consistency() {
    jl_project_state_run_validator delivery "$1"
}

# Validate all v1.1 project-state and filesystem invariants used by normal
# workflow commands. JSON Schema validation remains a separate caller step.
jl_project_validate_state() {
    jl_project_state_run_validator all "$1"
}

# Return the derived status for one revision number.
jl_project_revision_status() {
    local manifest number current approved exists
    manifest="$1"
    number="$2"
    exists="$(jq --argjson number "$number" '[.revisions[] | select(.number == $number)] | length' "$manifest")" || return $?
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

# Return Setup, In progress, Approved, or Delivered. The validator performs all
# state and delivery checks before emitting the stage.
jl_project_state_derive() {
    jl_project_state_run_validator derive "$1"
}
