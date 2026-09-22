#!/usr/bin/env bash
# macOS/Linux portability helpers.
#
# BSD and GNU implementations differ for realpath, stat, checksum, and open.
# This module hides those differences from the rest of the application.
if [ "${JL_MIXING_PLATFORM_LOADED:-0}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi
JL_MIXING_PLATFORM_LOADED=1

JL_PLATFORM_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$JL_PLATFORM_LIB_DIR/common.sh"

# Normalize uname output to the supported macos or linux identifier.
jl_platform_name() {
    case "$(uname -s)" in
        Darwin) printf '%s\n' macos ;;
        Linux)  printf '%s\n' linux ;;
        *)      printf '%s\n' unsupported ;;
    esac
}

# Reject unsupported operating systems early.
jl_platform_require_supported() {
    local platform
    platform="$(jl_platform_name)"
    if [ "$platform" = "unsupported" ]; then
        jl_error "Unsupported operating system: $(uname -s)"
        return "$JL_EXIT_CONFIG"
    fi
}

# Expand a literal ~ or ~/ prefix without relying on eval.
jl_expand_home_path() {
    local path
    path="$1"
    case "$path" in
        '~') printf '%s\n' "$HOME" ;;
        \~/*) printf '%s/%s\n' "$HOME" "${path#\~/}" ;;
        *) printf '%s\n' "$path" ;;
    esac
}

# Resolve an existing path canonically, with a Python fallback for portability.
jl_realpath() {
    local path directory base
    path="$(jl_expand_home_path "$1")"

    if [ -d "$path" ]; then
        (cd "$path" && pwd -P)
        return
    fi

    directory="$(dirname "$path")"
    base="$(basename "$path")"
    if [ -d "$directory" ]; then
        directory="$(cd "$directory" && pwd -P)" || return $?
        printf '%s/%s\n' "$directory" "$base"
        return 0
    fi

    jl_require_command python3 "Python 3 is required for portable path handling." || return $?
    python3 - "$path" <<'PY_REALPATH'
# Python supplies realpath behavior on platforms lacking a suitable utility.
import os
import sys
print(os.path.realpath(sys.argv[1]))
PY_REALPATH
}

# Build an absolute path even when the final component does not exist.
jl_abspath_allow_missing() {
    local path absolute directory base
    path="$(jl_expand_home_path "$1")"
    case "$path" in
        /*) absolute="$path" ;;
        *) absolute="$PWD/$path" ;;
    esac

    directory="$(dirname "$absolute")"
    base="$(basename "$absolute")"
    if [ -d "$directory" ]; then
        directory="$(cd "$directory" && pwd -P)" || return $?
        printf '%s/%s\n' "$directory" "$base"
        return 0
    fi

    jl_require_command python3 "Python 3 is required for portable path handling." || return $?
    python3 - "$absolute" <<'PY_ABSPATH'
# abspath normalizes dot segments without requiring the final path to exist.
import os
import sys
print(os.path.abspath(sys.argv[1]))
PY_ABSPATH
}

# Return file size using the platform-appropriate stat syntax.
jl_stat_size() {
    local path
    path="$1"
    if stat -f '%z' "$path" >/dev/null 2>&1; then
        stat -f '%z' "$path"
    else
        stat -c '%s' "$path"
    fi
}

# Return numeric permission bits using BSD or GNU stat.
jl_stat_mode() {
    local path
    path="$1"
    if stat -f '%Lp' "$path" >/dev/null 2>&1; then
        stat -f '%Lp' "$path"
    else
        stat -c '%a' "$path"
    fi
}

# Return the filesystem device identifier using BSD or GNU stat.
# Comparing this value lets directory transactions reject cross-filesystem
# staging, where rename would no longer be atomic.
jl_stat_device() {
    local path
    path="$1"
    if stat -f '%d' "$path" >/dev/null 2>&1; then
        stat -f '%d' "$path"
    else
        stat -c '%d' "$path"
    fi
}

# Calculate a SHA-256 digest using the available platform utility.
jl_sha256() {
    local path
    path="$1"
    if jl_command_exists shasum; then
        shasum -a 256 "$path" | awk '{print $1}'
    elif jl_command_exists sha256sum; then
        sha256sum "$path" | awk '{print $1}'
    else
        jl_error "No SHA-256 utility is available."
        return "$JL_EXIT_CONFIG"
    fi
}

# Create a temporary file beside a target so final rename remains atomic.
# Use ordinary exclusive creation so SMB/NAS ACLs inherit from the parent.
jl_mktemp_file_near() {
    local target directory base candidate attempt
    target="$1"
    directory="$(dirname "$target")"
    base="$(basename "$target")"
    mkdir -p "$directory"
    attempt=0
    while [ "$attempt" -lt 32 ]; do
        candidate="$directory/.${base}.tmp.$$.$RANDOM.$attempt"
        if (set -C; : > "$candidate") 2>/dev/null; then
            printf '%s\n' "$candidate"
            return 0
        fi
        attempt=$((attempt + 1))
    done
    jl_error "Unable to allocate temporary file beside: $target"
    return "$JL_EXIT_GENERAL"
}

# Create a unique temporary directory beside a target using normal ACL inheritance.
jl_mktemp_dir_near() {
    local target directory base candidate attempt
    target="$1"
    directory="$(dirname "$target")"
    base="$(basename "$target")"
    attempt=0
    while [ "$attempt" -lt 32 ]; do
        candidate="$directory/.${base}.tmp.$$.$RANDOM.$attempt"
        if mkdir "$candidate" 2>/dev/null; then
            printf '%s\n' "$candidate"
            return 0
        fi
        attempt=$((attempt + 1))
    done
    jl_error "Unable to allocate temporary directory beside: $target"
    return "$JL_EXIT_GENERAL"
}

# Create a portable temporary directory for isolated work.
jl_mktemp_dir() {
    local prefix
    prefix="${1:-jl-mixing}"
    mktemp -d "${TMPDIR:-/tmp}/${prefix}.XXXXXX"
}

# Open a path in the platform file manager when supported.
jl_open_path() {
    local path
    path="$1"
    case "$(jl_platform_name)" in
        macos) open "$path" ;;
        linux)
            if jl_command_exists xdg-open; then
                xdg-open "$path"
            else
                jl_error "xdg-open is not installed."
                return "$JL_EXIT_CONFIG"
            fi
            ;;
        *) jl_platform_require_supported ;;
    esac
}
