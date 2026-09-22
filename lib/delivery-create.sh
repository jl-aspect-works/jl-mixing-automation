#!/usr/bin/env bash
# Shared delivery-creation service used by the Automation API.
#
# create-delivery remains the authoritative implementation body. Sourcing it
# here lets machine-facing callers execute that exact implementation in-process
# without launching the human command as a subprocess.
set -eu

DELIVERY_SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DELIVERY_SERVICE_ROOT="${JL_MIXING_HOME:-$(cd "$DELIVERY_SERVICE_DIR/.." && pwd)}"

jl_delivery_create_command() {
    # shellcheck source=bin/create-delivery
    . "$DELIVERY_SERVICE_ROOT/bin/create-delivery"
}
