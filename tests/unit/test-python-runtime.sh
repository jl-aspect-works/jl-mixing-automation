#!/usr/bin/env bash
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
python="${JL_MIXING_PYTHON:-$(command -v python3 || true)}"
[ -n "$python" ] || { echo "Missing Python 3" >&2; exit 1; }

PYTHONPATH="$ROOT/src" "$python" -m unittest discover -s "$ROOT/tests/python" -p 'test_*.py'
