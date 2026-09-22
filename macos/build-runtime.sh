#!/usr/bin/env bash
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="${1:-$ROOT/runtime}"
PYTHON="${JL_MIXING_BUILD_PYTHON:-$(command -v python3 || true)}"

[ -n "$PYTHON" ] || { echo "Error: Python 3 is required to build the macOS runtime." >&2; exit 3; }
"$PYTHON" -c 'import PyInstaller' 2>/dev/null || {
    echo "Error: PyInstaller is not installed. Install packaging/macos-build-requirements.txt first." >&2
    exit 3
}

case "$OUTPUT_DIR" in
    /*) ;;
    *) OUTPUT_DIR="$PWD/$OUTPUT_DIR" ;;
esac

work_root="$(mktemp -d "${TMPDIR:-/tmp}/jl-mixing-pyinstaller.XXXXXX")"
cleanup() { rm -rf -- "$work_root"; }
trap cleanup EXIT HUP INT TERM

dist="$work_root/dist"
work="$work_root/work"
spec="$work_root/spec"
mkdir -p "$dist" "$work" "$spec"

"$PYTHON" -m PyInstaller \
    --noconfirm \
    --clean \
    --onedir \
    --console \
    --name python \
    --paths "$ROOT/src" \
    --distpath "$dist" \
    --workpath "$work" \
    --specpath "$spec" \
    "$ROOT/macos/runtime_bootstrap.py"

built="$dist/python"
[ -x "$built/python" ] || {
    echo "Error: PyInstaller output is missing executable python." >&2
    exit 3
}

rm -rf -- "$OUTPUT_DIR"
mkdir -p "$(dirname "$OUTPUT_DIR")"
mv "$built" "$OUTPUT_DIR"

printf 'Built JL Mixing macOS runtime: %s\n' "$OUTPUT_DIR"
