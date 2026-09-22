#!/usr/bin/env bash
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
version="$(tr -d '[:space:]' < "$ROOT/VERSION")"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/jl-mixing-macos-install.XXXXXX")"
cleanup() { rm -rf -- "$tmp"; }
trap cleanup EXIT HUP INT TERM

dist="$tmp/dist"
extract="$tmp/extract"
prefix="$tmp/prefix"
home="$tmp/home"
fakebin="$tmp/fakebin"
workspace="$tmp/workspace"
mkdir -p "$dist" "$extract" "$home" "$fakebin"

"$ROOT/tools/build-release" --platform macos --output-dir "$dist" >/dev/null
archive="$dist/jl-mixing-$version-macos.tar.gz"
[ -f "$archive" ] || { echo "[FAIL] macOS release archive exists" >&2; exit 1; }
tar -xzf "$archive" -C "$extract"
package="$extract/jl-mixing-$version"
[ -x "$package/runtime/python" ] || { echo "[FAIL] extracted runtime exists" >&2; exit 1; }
[ -x "$package/macos/install.sh" ] || { echo "[FAIL] extracted macOS installer exists" >&2; exit 1; }

echo '# user zsh content' > "$home/.zshrc"
for command_name in python3 jq; do
    cat > "$fakebin/$command_name" <<'EOF_STUB'
#!/usr/bin/env bash
echo "unexpected external dependency: $0" >&2
exit 97
EOF_STUB
    chmod +x "$fakebin/$command_name"
done

export HOME="$home"
export SHELL="/bin/zsh"
export PATH="$fakebin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
unset PYTHONPATH

"$package/macos/install.sh" --prefix "$prefix" >/dev/null
echo "[PASS] macOS installer succeeds without external Python or jq"

app="$prefix/share/jl-mixing"
bin="$prefix/bin"
[ -x "$app/runtime/python" ] || { echo "[FAIL] installed bundled runtime exists" >&2; exit 1; }
[ -x "$bin/jl-mixing" ] || { echo "[FAIL] installed jl-mixing launcher exists" >&2; exit 1; }
grep -q '# user zsh content' "$home/.zshrc"
grep -q '# >>> JL Mixing managed configuration >>>' "$home/.zshrc"
echo "[PASS] installer preserves user shell content and adds managed block"

"$bin/jl-mixing" system-info --json > "$tmp/system-info.json"
"$app/runtime/python" -m jl_mixing.cli system-info --json > "$tmp/runtime-system-info.json"
grep -Eq '"api_version"[[:space:]]*:[[:space:]]*"1\.0"' "$tmp/system-info.json"
grep -Eq '"api_version"[[:space:]]*:[[:space:]]*"1\.0"' "$tmp/runtime-system-info.json"
echo "[PASS] installed command and direct runtime report API 1.0"

"$bin/new-studio" --root "$workspace" --name 'Self Contained Studio' --no-default-cd >/dev/null
[ -f "$workspace/Studio/studio.json" ] || { echo "[FAIL] installed new-studio creates workspace" >&2; exit 1; }
echo "[PASS] installed workflow creates workspace"

sentinel="$app/rollback-sentinel.txt"
printf 'stable\n' > "$sentinel"
export JL_MIXING_TEST_FAIL_INSTALL_AT=after-application
if "$package/macos/install.sh" --prefix "$prefix" >/dev/null 2>"$tmp/install-failure.stderr"; then
    echo "[FAIL] injected macOS install failure is reported" >&2
    exit 1
fi
unset JL_MIXING_TEST_FAIL_INSTALL_AT
[ -f "$sentinel" ] || { echo "[FAIL] failed reinstall restores previous application" >&2; exit 1; }
[ "$(tr -d '\r\n' < "$sentinel")" = stable ] || { echo "[FAIL] rollback preserves application bytes" >&2; exit 1; }
grep -q '# user zsh content' "$home/.zshrc"
echo "[PASS] failed reinstall rolls back application and shell state"

"$bin/jl-mixing-uninstall" >/dev/null
[ ! -e "$app" ] || { echo "[FAIL] uninstaller removes application" >&2; exit 1; }
[ ! -e "$bin/jl-mixing" ] || { echo "[FAIL] uninstaller removes managed launcher" >&2; exit 1; }
[ -f "$workspace/Studio/studio.json" ] || { echo "[FAIL] uninstaller preserves workspace" >&2; exit 1; }
grep -q '# user zsh content' "$home/.zshrc"
if grep -q '# >>> JL Mixing managed configuration >>>' "$home/.zshrc"; then
    echo "[FAIL] uninstaller removes managed shell block" >&2
    exit 1
fi
echo "[PASS] uninstaller preserves workspace and user shell content"

echo "[OK] self-contained macOS installation lifecycle"
