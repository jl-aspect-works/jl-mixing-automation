#!/usr/bin/env bash
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
fake_bin="$tmp/fake bin"
result_tmp="$tmp/results"
mkdir -p "$fake_bin" "$result_tmp"

cat > "$fake_bin/new-client" <<'FAKE'
#!/usr/bin/env bash
set -eu
mode="${1:-success}"
case "$mode" in
    fail) exit 7 ;;
    no-result) exit 0 ;;
    invalid)
        printf 'relative/path\n' > "$JL_MIXING_CD_RESULT_FILE"
        exit 0
        ;;
    multiple)
        printf '/tmp/one\n/tmp/two\n' > "$JL_MIXING_CD_RESULT_FILE"
        exit 0
        ;;
    missing)
        printf '/definitely/missing/jl-mixing-directory\n' > "$JL_MIXING_CD_RESULT_FILE"
        exit 0
        ;;
    *)
        destination="${JL_TEST_DESTINATION:?}"
        mkdir -p "$destination"
        python3 - "$JL_MIXING_CD_RESULT_FILE" "$JL_TEST_MODE_FILE" <<'PY_MODE'
from pathlib import Path
import os, stat, sys
mode = stat.S_IMODE(os.stat(sys.argv[1]).st_mode)
Path(sys.argv[2]).write_text(oct(mode), encoding="utf-8")
PY_MODE
        printf '%s\n' "$destination" > "$JL_MIXING_CD_RESULT_FILE"
        ;;
esac
FAKE
chmod +x "$fake_bin/new-client"
ln -s new-client "$fake_bin/new-mix"
ln -s new-client "$fake_bin/new-revision"

integration="$ROOT/bin/jl-mixing-shell-integration"
destination="$tmp/Created Project With Spaces"
mode_file="$tmp/mode"

output="$(PATH="$fake_bin:$PATH" TMPDIR="$result_tmp" \
    JL_TEST_DESTINATION="$destination" JL_TEST_MODE_FILE="$mode_file" \
    bash -c '. "$1"; new-client success; pwd' _ "$integration")"
assert_contains "$output" "Entered: $destination" "wrapper prints truthful entered path"
assert_eq "$destination" "$(printf '%s\n' "$output" | tail -n 1)" "wrapper changes parent shell directory"
assert_eq "0o600" "$(cat "$mode_file")" "result file uses user-only permissions"
assert_eq "0" "$(find "$result_tmp" -type f | wc -l | tr -d ' ')" "result file cleaned after success"

trailing_destination="$tmp/Trailing Slash TMPDIR Client"
output="$(PATH="$fake_bin:$PATH" TMPDIR="$result_tmp/" \
    JL_TEST_DESTINATION="$trailing_destination" JL_TEST_MODE_FILE="$mode_file" \
    bash -c '. "$1"; new-client success; pwd' _ "$integration")"
assert_eq "$trailing_destination" "$(printf '%s\n' "$output" | tail -n 1)" \
    "trailing-slash TMPDIR supports automatic directory change"
assert_eq "0" "$(find "$result_tmp" -type f | wc -l | tr -d ' ')" \
    "trailing-slash TMPDIR result file cleaned"

assert_success "no result leaves command successful" env PATH="$fake_bin:$PATH" TMPDIR="$result_tmp" \
    bash -c '. "$1"; before=$PWD; new-client no-result; test "$PWD" = "$before"' _ "$integration"

set +e
PATH="$fake_bin:$PATH" TMPDIR="$result_tmp" bash -c '. "$1"; new-client fail' _ "$integration" >/dev/null 2>&1
status=$?
set -e
assert_eq "7" "$status" "wrapper preserves creation failure status"

assert_failure "relative result rejected" env PATH="$fake_bin:$PATH" TMPDIR="$result_tmp" \
    bash -c '. "$1"; new-client invalid' _ "$integration"
assert_failure "multiple results rejected" env PATH="$fake_bin:$PATH" TMPDIR="$result_tmp" \
    bash -c '. "$1"; new-client multiple' _ "$integration"
assert_failure "missing directory rejected" env PATH="$fake_bin:$PATH" TMPDIR="$result_tmp" \
    bash -c '. "$1"; new-client missing' _ "$integration"
assert_success "repeated sourcing is harmless" env PATH="$fake_bin:$PATH" TMPDIR="$result_tmp" \
    bash -c '. "$1"; . "$1"; command -V new-client >/dev/null' _ "$integration"
assert_failure "integration refuses standalone execution" "$integration"
assert_eq "0" "$(find "$result_tmp" -type f | wc -l | tr -d ' ')" "result files cleaned after failures"

if command -v zsh >/dev/null 2>&1; then
    zsh_destination="$tmp/Zsh Client"
    output="$(PATH="$fake_bin:$PATH" TMPDIR="$result_tmp" \
        JL_TEST_DESTINATION="$zsh_destination" JL_TEST_MODE_FILE="$mode_file" \
        zsh -c 'source "$1"; new-client success; pwd' _ "$integration")"
    assert_eq "$zsh_destination" "$(printf '%s\n' "$output" | tail -n 1)" "zsh wrapper changes directory"
else
    echo "[SKIP] zsh is not installed in this test environment."
fi

echo "[OK] shell integration ($TEST_COUNT assertions)"
