#!/usr/bin/env bash
# Shared intake-validation service used by the Automation API.
#
# validate-intake remains the authoritative implementation body. Sourcing it
# here lets machine-facing callers execute that exact implementation in-process
# without launching the human command as a subprocess.
set -eu

INTAKE_SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTAKE_SERVICE_ROOT="${JL_MIXING_HOME:-$(cd "$INTAKE_SERVICE_DIR/.." && pwd)}"

jl_intake_validate_command() {
    # shellcheck source=bin/validate-intake
    . "$INTAKE_SERVICE_ROOT/bin/validate-intake"
}
