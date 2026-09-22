#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -x "$ROOT/runtime/python" ] || { echo "Error: bundled macOS runtime is missing: $ROOT/runtime/python" >&2; exit 3; }
export JL_MIXING_HOME="$ROOT"
exec "$ROOT/runtime/python" -m jl_mixing.macos_installer install "$@"
