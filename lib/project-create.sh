#!/usr/bin/env bash
# Shared project-creation service used by the human CLI and Automation API.
#
# The implementation body is kept in project-create-command.sh so the original
# new-mix behavior can be reused byte-for-byte while callers share one in-process
# service entry point.
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="${JL_MIXING_HOME:-$(cd "$SCRIPT_DIR/.." && pwd)}"

jl_project_create_command() {
    # Source the preserved implementation into the caller shell. Human-facing
    # new-mix calls this directly; the Automation API calls it in a controlled
    # subshell so the implementation's historical exit behavior is preserved.
    # shellcheck source=lib/project-create-command.sh
    . "$APP_ROOT/lib/project-create-command.sh"
}
