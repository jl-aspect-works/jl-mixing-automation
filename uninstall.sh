#!/usr/bin/env bash
# Remove JL Mixing Automation application files, managed launchers, and the
# installer-managed shell block without touching studio workspaces.
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
Usage: jl-mixing-uninstall [--prefix PATH]
       ./uninstall.sh [--prefix PATH]

Options:
  --prefix PATH  Installation prefix (default: ~/.local)
  -h, --help     Show this help
USAGE
}

prefix="${JL_MIXING_INSTALL_PREFIX:-$HOME/.local}"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix)
            [ "$#" -ge 2 ] || { echo "Error: --prefix requires a value." >&2; exit 2; }
            [ -n "$2" ] || { echo "Error: --prefix requires a nonempty value." >&2; exit 2; }
            prefix="$2"
            shift 2
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

case "$prefix" in
    /*) ;;
    *) prefix="$PWD/$prefix" ;;
esac
prefix_parent="$(dirname "$prefix")"
prefix_base="$(basename "$prefix")"
if [ -d "$prefix_parent" ]; then
    prefix_parent="$(cd "$prefix_parent" && pwd -P)"
fi
prefix="$prefix_parent/$prefix_base"

app_dir="$prefix/share/jl-mixing"
bin_dir="$prefix/bin"
state_file="$app_dir/install-state.json"
helper="$app_dir/tools/manage-shell-config.py"

is_managed_launcher() {
    [ -f "$1" ] && [ ! -L "$1" ] && grep -q 'JL Mixing Automation managed launcher' "$1" 2>/dev/null
}

is_managed_integration() {
    [ -f "$1" ] && [ ! -L "$1" ] && grep -q 'JL Mixing Automation managed shell integration' "$1" 2>/dev/null
}

uninstall_maybe_fail() {
    if [ "${JL_MIXING_TEST_FAIL_UNINSTALL_AT:-}" = "$1" ]; then
        echo "Error: injected uninstall failure at $1" >&2
        return 1
    fi
}

[ -x "$helper" ] || {
    # Source-tree use during development may not have an installed helper.
    source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    helper="$source_root/tools/manage-shell-config.py"
}
[ -x "$helper" ] || { echo "Error: shell-configuration helper is unavailable." >&2; exit 5; }
command -v python3 >/dev/null 2>&1 || { echo "Error: Python 3 is required for uninstall." >&2; exit 3; }

startup_file=""
shell_cleanup=0
startup_file_created=false
startup_file_added_separator=false
state_valid=0
if [ -f "$state_file" ] && jq -e \
        --arg prefix "$prefix" \
        '.installation_prefix == $prefix and (.shell_integration.enabled | type == "boolean")' \
        "$state_file" >/dev/null 2>&1; then
    state_valid=1
    if jq -e '.shell_integration.enabled == true' "$state_file" >/dev/null; then
        startup_file="$(jq -r '.shell_integration.startup_file' "$state_file")"
        [ -n "$startup_file" ] || { echo "Error: install-state shell startup path is empty." >&2; exit 5; }
        case "$startup_file" in
            "$HOME/.zshrc"|"$HOME/.bashrc") ;;
            *) echo "Error: install-state references a non-user shell startup file: $startup_file" >&2; exit 5 ;;
        esac
        python3 "$helper" validate "$startup_file" | grep -q '^present$' || {
            echo "Error: managed shell configuration could not be validated; uninstall did not proceed." >&2
            exit 5
        }
        shell_cleanup=1
        if jq -e '.shell_integration.startup_file_created == true' "$state_file" >/dev/null 2>&1; then
            startup_file_created=true
        fi
        if jq -e '.shell_integration.startup_file_added_separator == true' "$state_file" >/dev/null 2>&1; then
            startup_file_added_separator=true
        fi
    fi
fi

# Conservative fallback for installations whose state record is missing or
# invalid. Remove a shell block only when exactly one unambiguous user-level
# startup file contains it.
if [ "$state_valid" -eq 0 ]; then
    present_count=0
    detected_file=""
    for candidate in "$HOME/.zshrc" "$HOME/.bashrc"; do
        status="$(python3 "$helper" validate "$candidate")" || {
            echo "Error: malformed JL Mixing shell markers were found in: $candidate" >&2
            echo "Remove the managed marker block manually before retrying uninstall." >&2
            exit 5
        }
        if [ "$status" = "present" ]; then
            present_count=$((present_count + 1))
            detected_file="$candidate"
        fi
    done
    if [ "$present_count" -gt 1 ]; then
        echo "Error: multiple JL Mixing shell blocks were found; uninstall did not proceed." >&2
        exit 5
    fi
    if [ "$present_count" -eq 1 ]; then
        startup_file="$detected_file"
        shell_cleanup=1
    fi
fi

public_commands='jl-mixing
new-studio
new-client
new-mix
validate-intake
new-revision
approve-mix
create-delivery
complete-project
jl-mixing-shell-integration
jl-mixing-uninstall'

# Validate every file before changing the active installation. Unmanaged files
# are preserved and reported, not treated as application-owned content.
while IFS= read -r public_name; do
    [ -n "$public_name" ] || continue
    candidate="$bin_dir/$public_name"
    [ -e "$candidate" ] || continue
    case "$public_name" in
        jl-mixing-shell-integration)
            is_managed_integration "$candidate" || printf 'Preserved unmanaged file: %s\n' "$candidate" >&2
            ;;
        *)
            is_managed_launcher "$candidate" || printf 'Preserved unmanaged file: %s\n' "$candidate" >&2
            ;;
    esac
done <<EOF_PUBLIC
$public_commands
EOF_PUBLIC

backup_root="$(create_inherited_temp_dir "$prefix" ".jl-mixing-uninstall-backup")"
mkdir -p "$backup_root/bin"
staged_startup=""
shell_file_existed=0
commit_started=0

rollback_uninstall() {
    status=$?
    trap - EXIT HUP INT TERM
    rollback_failed=0
    set +e
    if [ "$status" -ne 0 ] && [ "$commit_started" -eq 1 ]; then
        echo "Uninstall failed; restoring JL Mixing Automation." >&2
        rm -rf -- "$app_dir"
        if [ -d "$backup_root/app" ]; then
            mkdir -p "$(dirname "$app_dir")"
            mv "$backup_root/app" "$app_dir" || rollback_failed=1
        fi
        while IFS= read -r public_name; do
            [ -n "$public_name" ] || continue
            current="$bin_dir/$public_name"
            if [ -e "$backup_root/bin/$public_name" ]; then
                rm -rf -- "$current"
                mkdir -p "$bin_dir"
                cp -p "$backup_root/bin/$public_name" "$current" || rollback_failed=1
            fi
        done <<EOF_RESTORE
$public_commands
EOF_RESTORE
        if [ "$shell_cleanup" -eq 1 ]; then
            if [ "$shell_file_existed" -eq 1 ] && [ -f "$backup_root/startup-file" ]; then
                cp -p "$backup_root/startup-file" "$startup_file" || rollback_failed=1
            else
                rm -f -- "$startup_file"
            fi
        fi
    fi
    if [ "$rollback_failed" -eq 0 ]; then
        rm -rf -- "$backup_root"
    else
        echo "Error: uninstall rollback was incomplete; recovery files remain at: $backup_root" >&2
    fi
    [ -z "$staged_startup" ] || rm -f -- "$staged_startup"
    set -e
    exit "$status"
}
trap rollback_uninstall EXIT HUP INT TERM

if [ "$shell_cleanup" -eq 1 ]; then
    staged_startup="$backup_root/startup-updated"
    if [ -f "$startup_file" ]; then
        cp -p "$startup_file" "$backup_root/startup-file"
        cp -p "$startup_file" "$staged_startup"
        shell_file_existed=1
    else
        echo "Error: configured shell startup file is missing: $startup_file" >&2
        exit 5
    fi
    python3 "$helper" remove "$staged_startup" --require-present
    if [ "$startup_file_added_separator" = true ]; then
        python3 - "$staged_startup" <<'PY_TRIM_SEPARATOR'
from pathlib import Path
import sys
path = Path(sys.argv[1])
data = path.read_bytes()
if not data.endswith(b"\n"):
    raise SystemExit("expected installer-added shell separator newline")
path.write_bytes(data[:-1])
PY_TRIM_SEPARATOR
    fi
fi

commit_started=1

# Shell cleanup comes first. If anything later fails, rollback restores it.
if [ "$shell_cleanup" -eq 1 ]; then
    startup_temp="$startup_file.jl-mixing-uninstall.$$"
    cp -p "$staged_startup" "$startup_temp"
    mv "$startup_temp" "$startup_file"
fi
uninstall_maybe_fail after-shell

# Move workflow launchers and integration into same-prefix backup staging.
while IFS= read -r public_name; do
    [ -n "$public_name" ] || continue
    [ "$public_name" != "jl-mixing-uninstall" ] || continue
    candidate="$bin_dir/$public_name"
    [ -e "$candidate" ] || continue
    managed=0
    if [ "$public_name" = "jl-mixing-shell-integration" ]; then
        is_managed_integration "$candidate" && managed=1
    else
        is_managed_launcher "$candidate" && managed=1
    fi
    if [ "$managed" -eq 1 ]; then
        cp -p "$candidate" "$backup_root/bin/$public_name"
        rm -f -- "$candidate"
    fi
done <<EOF_REMOVE_PUBLIC
$public_commands
EOF_REMOVE_PUBLIC
uninstall_maybe_fail after-launchers

if [ -d "$app_dir" ]; then
    mv "$app_dir" "$backup_root/app"
fi
uninstall_maybe_fail after-application
verification_helper="$helper"
if [ -x "$backup_root/app/tools/manage-shell-config.py" ]; then
    verification_helper="$backup_root/app/tools/manage-shell-config.py"
fi

# Remove the uninstaller launcher last so it remains available throughout all
# earlier cleanup steps.
if [ -e "$bin_dir/jl-mixing-uninstall" ] && is_managed_launcher "$bin_dir/jl-mixing-uninstall"; then
    cp -p "$bin_dir/jl-mixing-uninstall" "$backup_root/bin/jl-mixing-uninstall"
    rm -f -- "$bin_dir/jl-mixing-uninstall"
fi

[ ! -e "$app_dir" ] || exit 5
for removed in jl-mixing new-studio new-client new-mix validate-intake new-revision approve-mix create-delivery \
        jl-mixing-shell-integration jl-mixing-uninstall; do
    if [ -e "$bin_dir/$removed" ]; then
        case "$removed" in
            jl-mixing-shell-integration)
                is_managed_integration "$bin_dir/$removed" && exit 5
                ;;
            *)
                is_managed_launcher "$bin_dir/$removed" && exit 5
                ;;
        esac
    fi
done
if [ "$shell_cleanup" -eq 1 ]; then
    python3 "$verification_helper" validate "$startup_file" | grep -q '^absent$' || exit 5
fi

rm -rf -- "$backup_root"
backup_root=""
commit_started=0
trap - EXIT HUP INT TERM

if [ "$shell_cleanup" -eq 1 ] && [ "$startup_file_created" = true ] && [ -f "$startup_file" ] && [ ! -s "$startup_file" ]; then
    rm -f -- "$startup_file"
fi

printf 'JL Mixing Automation uninstalled successfully.\n\n'
printf 'Removed application:\n  %s\n' "$app_dir"
if [ "$shell_cleanup" -eq 1 ]; then
    printf '\nUpdated shell configuration:\n  %s\n' "$startup_file"
fi
printf '\nStudio workspaces were not modified.\n'
printf '\nOpen a new Terminal window or tab to remove JL Mixing from the current shell environment.\n'
