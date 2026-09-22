#!/usr/bin/env bash
# Install or upgrade JL Mixing Automation under a user-selected prefix.
#
# The complete application, private Python runtime, public launchers, shell
# integration, and managed startup-file block are staged and verified before
# the active installation is changed. A failed commit restores the prior
# application, launchers, and shell configuration together.
set -eu

create_inherited_temp_dir() {
    local parent prefix candidate attempt
    parent="$1"
    prefix="$2"
    attempt=0
    while [ "$attempt" -lt 32 ]; do
        candidate="$parent/$prefix.$$.$RANDOM.$attempt"
        if mkdir "$candidate" 2>/dev/null; then
            printf '%s\n' "$candidate"
            return 0
        fi
        attempt=$((attempt + 1))
    done
    echo "Error: unable to allocate staging directory in $parent" >&2
    return 1
}

usage() {
    cat <<'USAGE'
Usage: ./install.sh [options]

Options:
  --prefix PATH             Installation prefix (default: ~/.local)
  --no-shell-integration    Do not modify shell startup configuration
  -h, --help                Show this help

Installed locations:
  Application: PREFIX/share/jl-mixing
  Commands:    PREFIX/bin
USAGE
}

prefix="${JL_MIXING_INSTALL_PREFIX:-$HOME/.local}"
prefix_seen=0
shell_integration_requested=1

while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix)
            [ "$#" -ge 2 ] || { echo "Error: --prefix requires a value." >&2; exit 2; }
            [ "$prefix_seen" -eq 0 ] || { echo "Error: --prefix may be supplied only once." >&2; exit 2; }
            [ -n "$2" ] || { echo "Error: --prefix requires a nonempty value." >&2; exit 2; }
            prefix="$2"
            prefix_seen=1
            shift 2
            ;;
        --no-shell-integration)
            shell_integration_requested=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Error: unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

canonicalize_destination() {
    local requested parent base
    requested="$1"
    case "$requested" in
        /*) ;;
        *) requested="$PWD/$requested" ;;
    esac
    parent="$(dirname "$requested")"
    base="$(basename "$requested")"
    mkdir -p "$parent"
    parent="$(cd "$parent" && pwd -P)"
    printf '%s/%s\n' "$parent" "$base"
}

single_quote_shell() {
    printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\"'\"'/g")"
}

is_managed_launcher() {
    [ -f "$1" ] && [ ! -L "$1" ] && grep -q 'JL Mixing Automation managed launcher' "$1" 2>/dev/null
}

is_managed_integration() {
    [ -f "$1" ] && [ ! -L "$1" ] && grep -q 'JL Mixing Automation managed shell integration' "$1" 2>/dev/null
}

install_maybe_fail() {
    if [ "${JL_MIXING_TEST_FAIL_INSTALL_AT:-}" = "$1" ]; then
        echo "Error: injected installation failure at $1" >&2
        return 1
    fi
}

prefix="$(canonicalize_destination "$prefix")"
app_dir="$prefix/share/jl-mixing"
bin_dir="$prefix/bin"
share_dir="$prefix/share"
state_file="$app_dir/install-state.json"

required_paths='VERSION
API_VERSION
LICENSE
README.md
CHANGELOG.md
bin
lib
src
api
schemas
templates
docs
tools/validate-json.py
tools/build-intake-report.py
tools/project-state.py
tools/import-project-source.py
tools/import-revision-source.py
tools/build-delivery.py
tools/manage-shell-config.py
packaging/requirements.txt
uninstall.sh'

while IFS= read -r relative_path; do
    [ -n "$relative_path" ] || continue
    [ -e "$SOURCE_ROOT/$relative_path" ] || {
        echo "Error: installation package is missing $relative_path" >&2
        exit 3
    }
done <<EOF_REQUIRED
$required_paths
EOF_REQUIRED

command -v bash >/dev/null 2>&1 || { echo "Error: Bash is required." >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { echo "Error: Python 3.10 or newer is required." >&2; exit 3; }
command -v jq >/dev/null 2>&1 || { echo "Error: jq is required." >&2; exit 3; }
python3 - <<'PY_VERSION' || exit 3
import sys
if sys.version_info < (3, 10):
    print("Error: Python 3.10 or newer is required.", file=sys.stderr)
    raise SystemExit(1)
PY_VERSION
python3 -m venv --help >/dev/null 2>&1 || {
    echo "Error: Python venv support is required." >&2
    exit 3
}

shell_name=""
startup_file=""
shell_integration_enabled=0
startup_file_created=false
startup_file_added_separator=false
shell_block_status="absent"
if [ "$shell_integration_requested" -eq 1 ]; then
    configured_shell="${SHELL:-}"
    shell_name="$(basename "$configured_shell" 2>/dev/null || true)"
    case "$shell_name" in
        zsh)
            startup_file="$HOME/.zshrc"
            shell_integration_enabled=1
            ;;
        bash)
            startup_file="$HOME/.bashrc"
            shell_integration_enabled=1
            ;;
        *)
            shell_name=""
            startup_file=""
            shell_integration_enabled=0
            ;;
    esac
fi

if [ "$shell_integration_enabled" -eq 1 ]; then
    shell_block_status="$(python3 "$SOURCE_ROOT/tools/manage-shell-config.py" validate "$startup_file")" || exit 5
    if [ ! -e "$startup_file" ]; then
        startup_file_created=true
    elif [ -f "$state_file" ] &&             jq -e --arg file "$startup_file"                 '.shell_integration.startup_file == $file and .shell_integration.startup_file_created == true'                 "$state_file" >/dev/null 2>&1; then
        startup_file_created=true
    fi
    if [ "$shell_block_status" = "absent" ] && [ -s "$startup_file" ]; then
        if ! python3 - "$startup_file" <<'PY_FINAL_NEWLINE'
from pathlib import Path
import sys
data = Path(sys.argv[1]).read_bytes()
raise SystemExit(0 if data.endswith((b"\n", b"\r")) else 1)
PY_FINAL_NEWLINE
        then
            startup_file_added_separator=true
        fi
    elif [ -f "$state_file" ] &&             jq -e --arg file "$startup_file"                 '.shell_integration.startup_file == $file and .shell_integration.startup_file_added_separator == true'                 "$state_file" >/dev/null 2>&1; then
        startup_file_added_separator=true
    fi
fi

# When shell configuration is intentionally left untouched, retain prior state
# metadata if a previous managed block remains active. This lets a later
# uninstall remove the block conservatively.
if [ "$shell_integration_enabled" -eq 0 ] && [ -f "$state_file" ]; then
    if jq -e '.shell_integration.enabled == true and (.shell_integration.startup_file | type == "string")' \
            "$state_file" >/dev/null 2>&1; then
        previous_startup="$(jq -r '.shell_integration.startup_file' "$state_file")"
        previous_shell="$(jq -r '.shell_integration.shell' "$state_file")"
        if [ -n "$previous_startup" ] && [ -f "$previous_startup" ] && \
                python3 "$SOURCE_ROOT/tools/manage-shell-config.py" validate "$previous_startup" \
                    2>/dev/null | grep -q '^present$'; then
            shell_name="$previous_shell"
            startup_file="$previous_startup"
            if jq -e '.shell_integration.startup_file_created == true' "$state_file" >/dev/null 2>&1; then
                startup_file_created=true
            fi
            if jq -e '.shell_integration.startup_file_added_separator == true' "$state_file" >/dev/null 2>&1; then
                startup_file_added_separator=true
            fi
            # State remains enabled because the existing block remains active,
            # but this installation run will not edit it.
            shell_integration_enabled=2
        fi
    fi
fi

mkdir -p "$prefix" "$share_dir" "$bin_dir"

public_commands='jl-mixing
new-studio
new-client
new-mix
validate-intake
new-revision
approve-mix
create-delivery'

while IFS= read -r command_name; do
    [ -n "$command_name" ] || continue
    destination="$bin_dir/$command_name"
    if [ -e "$destination" ] && ! is_managed_launcher "$destination"; then
        echo "Error: refusing to overwrite unmanaged command: $destination" >&2
        exit 5
    fi
done <<EOF_COMMANDS
$public_commands
EOF_COMMANDS

integration_destination="$bin_dir/jl-mixing-shell-integration"
if [ -e "$integration_destination" ] && ! is_managed_integration "$integration_destination"; then
    echo "Error: refusing to overwrite unmanaged shell integration: $integration_destination" >&2
    exit 5
fi
uninstall_destination="$bin_dir/jl-mixing-uninstall"
if [ -e "$uninstall_destination" ] && ! is_managed_launcher "$uninstall_destination"; then
    echo "Error: refusing to overwrite unmanaged uninstaller: $uninstall_destination" >&2
    exit 5
fi

legacy_complete="$bin_dir/complete-project"
legacy_complete_managed=0
if [ -e "$legacy_complete" ] && is_managed_launcher "$legacy_complete"; then
    legacy_complete_managed=1
fi

stage_root="$(create_inherited_temp_dir "$prefix" ".jl-mixing-install-stage")"
backup_root=""
commit_started=0
shell_file_existed=0

rollback_install() {
    status=$?
    trap - EXIT HUP INT TERM
    rollback_failed=0
    set +e
    if [ "$status" -ne 0 ]; then
        echo "Installation failed; restoring the previous version." >&2
        if [ "$commit_started" -eq 1 ] && [ -n "$backup_root" ] && [ -d "$backup_root" ]; then
            rm -rf -- "$app_dir"
            if [ -d "$backup_root/app" ]; then
                mkdir -p "$(dirname "$app_dir")"
                mv "$backup_root/app" "$app_dir" || rollback_failed=1
            fi

            while IFS= read -r public_name; do
                [ -n "$public_name" ] || continue
                current="$bin_dir/$public_name"
                # Preflight guarantees these command names were absent or
                # JL-managed. Any current entry therefore belongs to the failed
                # installation attempt and may be removed before restoration.
                rm -rf -- "$current"
                if [ -f "$backup_root/bin/$public_name" ]; then
                    mkdir -p "$bin_dir"
                    cp -p "$backup_root/bin/$public_name" "$current" || rollback_failed=1
                fi
            done <<EOF_ROLLBACK_PUBLIC
$public_commands
jl-mixing-shell-integration
jl-mixing-uninstall
complete-project
EOF_ROLLBACK_PUBLIC

            if [ "$shell_integration_enabled" -eq 1 ]; then
                if [ "$shell_file_existed" -eq 1 ] && [ -f "$backup_root/startup-file" ]; then
                    cp -p "$backup_root/startup-file" "$startup_file" || rollback_failed=1
                else
                    rm -f -- "$startup_file"
                fi
            fi
        fi
    fi
    rm -rf -- "$stage_root"
    if [ "$rollback_failed" -eq 0 ]; then
        [ -z "$backup_root" ] || rm -rf -- "$backup_root"
    else
        echo "Error: installation rollback was incomplete; recovery files remain at: $backup_root" >&2
    fi
    set -e
    exit "$status"
}
trap rollback_install EXIT HUP INT TERM

stage_app="$stage_root/share/jl-mixing"
stage_bin="$stage_root/bin"
mkdir -p "$stage_app/bin" "$stage_app/lib" "$stage_app/src" "$stage_app/api" "$stage_app/schemas" \
    "$stage_app/templates" "$stage_app/docs" "$stage_app/tools" \
    "$stage_app/packaging" "$stage_bin"

cp "$SOURCE_ROOT/VERSION" "$SOURCE_ROOT/API_VERSION" "$SOURCE_ROOT/LICENSE" \
    "$SOURCE_ROOT/README.md" "$SOURCE_ROOT/CHANGELOG.md" "$stage_app/"
cp -R "$SOURCE_ROOT/bin/." "$stage_app/bin/"
cp -R "$SOURCE_ROOT/lib/." "$stage_app/lib/"
cp -R "$SOURCE_ROOT/src/." "$stage_app/src/"
cp -R "$SOURCE_ROOT/api/." "$stage_app/api/"
cp -R "$SOURCE_ROOT/schemas/." "$stage_app/schemas/"
cp -R "$SOURCE_ROOT/templates/." "$stage_app/templates/"
cp -R "$SOURCE_ROOT/docs/." "$stage_app/docs/"
cp "$SOURCE_ROOT/tools/validate-json.py" "$SOURCE_ROOT/tools/build-intake-report.py" \
    "$SOURCE_ROOT/tools/project-state.py" "$SOURCE_ROOT/tools/import-project-source.py" \
    "$SOURCE_ROOT/tools/import-revision-source.py" "$SOURCE_ROOT/tools/build-delivery.py" \
    "$SOURCE_ROOT/tools/manage-shell-config.py" "$stage_app/tools/"
cp "$SOURCE_ROOT/packaging/requirements.txt" "$stage_app/packaging/"
cp "$SOURCE_ROOT/install.sh" "$SOURCE_ROOT/uninstall.sh" "$stage_app/"
if [ -d "$SOURCE_ROOT/packaging/vendor" ]; then
    cp -R "$SOURCE_ROOT/packaging/vendor" "$stage_app/packaging/"
fi
chmod +x "$stage_app/install.sh" "$stage_app/uninstall.sh" "$stage_app/bin/"* \
    "$stage_app/tools/"*.py

if [ "${JL_MIXING_TEST_SYSTEM_SITE_PACKAGES:-0}" = "1" ]; then
    mkdir -p "$stage_app/.venv/bin"
    test_python="$(command -v python3)"
    cat > "$stage_app/.venv/bin/python" <<EOF_TEST_PYTHON
#!/usr/bin/env bash
exec $(printf '%q' "$test_python") "\$@"
EOF_TEST_PYTHON
    chmod +x "$stage_app/.venv/bin/python"
else
    python3 -m venv "$stage_app/.venv"
fi

dependency_ready=0
if [ "${JL_MIXING_TEST_SYSTEM_SITE_PACKAGES:-0}" = "1" ]; then
    if "$stage_app/.venv/bin/python" - <<'PY_PRESENT'
from importlib.metadata import PackageNotFoundError, version
try:
    actual = version("jsonschema")
except PackageNotFoundError:
    raise SystemExit(1)
raise SystemExit(0 if actual == "4.26.0" else 1)
PY_PRESENT
    then dependency_ready=1; fi
fi
if [ "$dependency_ready" -eq 0 ]; then
    if [ -d "$stage_app/packaging/vendor" ] && find "$stage_app/packaging/vendor" -type f | grep -q .; then
        "$stage_app/.venv/bin/python" -m pip install --disable-pip-version-check --no-input \
            --no-index --find-links "$stage_app/packaging/vendor" \
            -r "$stage_app/packaging/requirements.txt"
    else
        "$stage_app/.venv/bin/python" -m pip install --disable-pip-version-check --no-input \
            -r "$stage_app/packaging/requirements.txt"
    fi
fi
"$stage_app/.venv/bin/python" - <<'PY_VERIFY'
from importlib.metadata import version
actual = version("jsonschema")
if actual != "4.26.0":
    raise SystemExit(f"jsonschema version mismatch: expected 4.26.0, found {actual}")
PY_VERIFY

quoted_app_dir="$(printf '%q' "$app_dir")"
write_launcher() {
    local command_name destination
    command_name="$1"
    destination="$stage_bin/$command_name"
    cat > "$destination" <<EOF_LAUNCHER
#!/usr/bin/env bash
# JL Mixing Automation managed launcher. Generated by install.sh.
export JL_MIXING_HOME=$quoted_app_dir
export JL_MIXING_PYTHON=$quoted_app_dir/.venv/bin/python
exec $quoted_app_dir/bin/$command_name "\$@"
EOF_LAUNCHER
    chmod +x "$destination"
}
while IFS= read -r command_name; do
    [ -n "$command_name" ] || continue
    write_launcher "$command_name"
done <<EOF_COMMANDS_STAGE
$public_commands
EOF_COMMANDS_STAGE

cp "$SOURCE_ROOT/bin/jl-mixing-shell-integration" "$stage_bin/jl-mixing-shell-integration"
chmod +x "$stage_bin/jl-mixing-shell-integration"
cat > "$stage_bin/jl-mixing-uninstall" <<EOF_UNINSTALL
#!/usr/bin/env bash
# JL Mixing Automation managed launcher. Generated by install.sh.
exec $quoted_app_dir/uninstall.sh --prefix $(printf '%q' "$prefix") "\$@"
EOF_UNINSTALL
chmod +x "$stage_bin/jl-mixing-uninstall"

shell_state_enabled=false
shell_state_name=""
shell_state_file=""
if [ "$shell_integration_enabled" -eq 1 ] || [ "$shell_integration_enabled" -eq 2 ]; then
    shell_state_enabled=true
    shell_state_name="$shell_name"
    shell_state_file="$startup_file"
fi
python3 - "$stage_app/install-state.json" "$prefix" "$shell_state_enabled" \
    "$shell_state_name" "$shell_state_file" "$startup_file_created" \
    "$startup_file_added_separator" <<'PY_STATE'
import json
from pathlib import Path
import sys
path, prefix, enabled, shell, startup, startup_created, added_separator = sys.argv[1:]
document = {
    "installation_prefix": prefix,
    "shell_integration": {
        "enabled": enabled == "true",
        "shell": shell,
        "startup_file": startup,
        "startup_file_created": startup_created == "true",
        "startup_file_added_separator": added_separator == "true",
    },
}
Path(path).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
PY_STATE

staged_startup=""
if [ "$shell_integration_enabled" -eq 1 ]; then
    block_file="$stage_root/shell-block"
    quoted_bin="$(single_quote_shell "$bin_dir")"
    cat > "$block_file" <<EOF_BLOCK
# >>> JL Mixing managed configuration >>>
export PATH=$quoted_bin:"\$PATH"

if command -v jl-mixing-shell-integration >/dev/null 2>&1; then
    source "\$(command -v jl-mixing-shell-integration)"
fi
# <<< JL Mixing managed configuration <<<
EOF_BLOCK
    staged_startup="$stage_root/startup-file"
    if [ -f "$startup_file" ]; then
        cp -p "$startup_file" "$staged_startup"
    else
        : > "$staged_startup"
        chmod 644 "$staged_startup"
    fi
    python3 "$SOURCE_ROOT/tools/manage-shell-config.py" install "$staged_startup" \
        --block-file "$block_file"
fi

# Verify the complete staged installation before touching the active version.
[ -x "$stage_app/.venv/bin/python" ]
[ -f "$stage_app/src/jl_mixing/__init__.py" ]
[ -f "$stage_app/install-state.json" ]
jq -e '.installation_prefix and (.shell_integration.enabled | type == "boolean")' \
    "$stage_app/install-state.json" >/dev/null
while IFS= read -r command_name; do
    [ -x "$stage_bin/$command_name" ] || { echo "Error: staged launcher missing: $command_name" >&2; exit 5; }
done <<EOF_VERIFY_PUBLIC
$public_commands
jl-mixing-shell-integration
jl-mixing-uninstall
EOF_VERIFY_PUBLIC
if [ "$shell_integration_enabled" -eq 1 ]; then
    python3 "$SOURCE_ROOT/tools/manage-shell-config.py" validate "$staged_startup" | grep -q '^present$'
fi

backup_root="$(create_inherited_temp_dir "$prefix" ".jl-mixing-install-backup")"
mkdir -p "$backup_root/bin"
commit_started=1

if [ -d "$app_dir" ]; then
    mv "$app_dir" "$backup_root/app"
fi
while IFS= read -r public_name; do
    [ -n "$public_name" ] || continue
    existing="$bin_dir/$public_name"
    if [ -e "$existing" ]; then
        cp -p "$existing" "$backup_root/bin/$public_name"
    fi
done <<EOF_BACKUP_PUBLIC
$public_commands
jl-mixing-shell-integration
jl-mixing-uninstall
EOF_BACKUP_PUBLIC
if [ "$legacy_complete_managed" -eq 1 ]; then
    cp -p "$legacy_complete" "$backup_root/bin/complete-project"
fi

if [ "$shell_integration_enabled" -eq 1 ]; then
    mkdir -p "$(dirname "$startup_file")"
    if [ -f "$startup_file" ]; then
        cp -p "$startup_file" "$backup_root/startup-file"
        shell_file_existed=1
    fi
fi

mkdir -p "$share_dir" "$bin_dir"
mv "$stage_app" "$app_dir"
install_maybe_fail after-application
while IFS= read -r public_name; do
    [ -n "$public_name" ] || continue
    public_temp="$bin_dir/.${public_name}.jl-mixing.$$"
    cp -p "$stage_bin/$public_name" "$public_temp"
    mv -f "$public_temp" "$bin_dir/$public_name"
done <<EOF_INSTALL_PUBLIC
$public_commands
jl-mixing-shell-integration
jl-mixing-uninstall
EOF_INSTALL_PUBLIC
if [ "$legacy_complete_managed" -eq 1 ]; then
    rm -f -- "$legacy_complete"
fi
install_maybe_fail after-launchers
if [ "$shell_integration_enabled" -eq 1 ]; then
    startup_temp="$startup_file.jl-mixing.$$"
    cp -p "$staged_startup" "$startup_temp"
    mv "$startup_temp" "$startup_file"
fi
install_maybe_fail after-shell

# Final verification happens against stable paths. Any failure triggers rollback.
[ -f "$app_dir/VERSION" ]
[ -x "$app_dir/.venv/bin/python" ]
[ -f "$app_dir/src/jl_mixing/__init__.py" ]
while IFS= read -r public_name; do
    [ -x "$bin_dir/$public_name" ] || exit 5
done <<EOF_FINAL_PUBLIC
$public_commands
jl-mixing-shell-integration
jl-mixing-uninstall
EOF_FINAL_PUBLIC
[ ! -e "$legacy_complete" ] || ! is_managed_launcher "$legacy_complete" || exit 5
if [ "$shell_integration_enabled" -eq 1 ]; then
    python3 "$app_dir/tools/manage-shell-config.py" validate "$startup_file" | grep -q '^present$'
fi

rm -rf -- "$backup_root"
backup_root=""
rm -rf -- "$stage_root"
stage_root=""
commit_started=0
trap - EXIT HUP INT TERM

version="$(cat "$app_dir/VERSION")"
printf 'Installed JL Mixing Automation %s\n' "$version"
printf 'Application: %s\n' "$app_dir"
printf 'Commands:    %s\n' "$bin_dir"
if [ "$shell_integration_enabled" -eq 1 ]; then
    printf 'Shell setup: %s\n' "$startup_file"
    echo
    echo "Open a new Terminal window or tab to activate JL Mixing."
    echo
    printf 'To activate it in this Terminal now:\n  source %s\n' "$(single_quote_shell "$startup_file")"
elif [ "$shell_integration_requested" -eq 0 ]; then
    echo "Shell setup: not modified (--no-shell-integration)"
    echo
    echo "Add the command directory to PATH:"
    printf '  export PATH=%s:"$PATH"\n' "$(single_quote_shell "$bin_dir")"
    echo "Automatic directory changes will fall back to copy-and-paste cd commands."
elif [ "$shell_integration_enabled" -eq 2 ]; then
    printf 'Shell setup: preserved existing configuration in %s\n' "$startup_file"
else
    echo "Shell setup: unsupported configured shell; no startup file was modified."
    echo
    echo "Add the command directory to PATH:"
    printf '  export PATH=%s:"$PATH"\n' "$(single_quote_shell "$bin_dir")"
fi

echo
echo "Next: new-studio"
