#!/usr/bin/env bash
# Shared revision-creation service used by the Automation API.
#
# new-revision remains the authoritative implementation body. Sourcing it here
# lets machine-facing callers execute that exact implementation in-process
# without launching the human command as a subprocess.
set -eu

REVISION_SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REVISION_SERVICE_ROOT="${JL_MIXING_HOME:-$(cd "$REVISION_SERVICE_DIR/.." && pwd)}"

jl_revision_create_command() {
    # shellcheck source=bin/new-revision
    . "$REVISION_SERVICE_ROOT/bin/new-revision"
}
