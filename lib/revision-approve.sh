#!/usr/bin/env bash
# Shared revision-approval service used by the Automation API.
#
# approve-mix remains the authoritative implementation body. Sourcing it here
# lets machine-facing callers execute that exact implementation in-process.
set -eu

APPROVAL_SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPROVAL_SERVICE_ROOT="${JL_MIXING_HOME:-$(cd "$APPROVAL_SERVICE_DIR/.." && pwd)}"

jl_revision_approve_command() {
    # shellcheck source=bin/approve-mix
    . "$APPROVAL_SERVICE_ROOT/bin/approve-mix"
}
