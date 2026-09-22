#!/usr/bin/env bash
# Safe filesystem primitives used by commands and transactional workflows.
#
# These helpers centralize overwrite protection, atomic writes, exact copies,
# safe moves, and the invariant that Original_Delivery is never modified.
if [ "${JL_MIXING_FILESYSTEM_LOADED:-0}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi
JL_MIXING_FILESYSTEM_LOADED=1

JL_FILESYSTEM_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$JL_FILESYSTEM_LIB_DIR/common.sh"
# shellcheck source=lib/platform.sh
. "$JL_FILESYSTEM_LIB_DIR/platform.sh"

# Create a directory tree if missing and accept an existing directory.
jl_fs_ensure_directory() {
    local path
    path="$1"
    if [ -e "$path" ] && [ ! -d "$path" ]; then
        jl_error "Cannot create directory because a non-directory exists: $path"
        return "$JL_EXIT_UNSAFE"
    fi
    mkdir -p "$path"
}

# Create a new directory but refuse any existing destination.
jl_fs_create_directory() {
    local path
    path="$1"
    if [ -e "$path" ]; then
        jl_error "Refusing to overwrite existing path: $path"
        return "$JL_EXIT_UNSAFE"
    fi
    mkdir -p "$path"
}

# Identify paths inside the immutable Original_Delivery subtree.
jl_fs_is_original_delivery_path() {
    local path
    path="$(jl_abspath_allow_missing "$1")" || return $?
    case "$path" in
        */01_Client_Files/Original_Delivery|*/01_Client_Files/Original_Delivery/*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# Reject any attempted write beneath Original_Delivery.
jl_fs_assert_mutable_path() {
    local path
    path="$1"
    if jl_fs_is_original_delivery_path "$path"; then
        jl_error "Unsafe operation prevented inside immutable Original_Delivery: $path"
        return "$JL_EXIT_UNSAFE"
    fi
}

# Copy one file without overwriting and verify the bytes are identical.
jl_fs_copy_file_exact() {
    local source destination
    source="$1"
    destination="$2"

    [ -f "$source" ] || {
        jl_error "Source file not found: $source"
        return "$JL_EXIT_VALIDATION"
    }
    jl_fs_assert_mutable_path "$destination" || return $?

    if [ -e "$destination" ]; then
        jl_error "Refusing to overwrite existing destination: $destination"
        return "$JL_EXIT_UNSAFE"
    fi

    mkdir -p "$(dirname "$destination")"
    cp -p "$source" "$destination"
}

# Copy a directory tree into a new destination without overwriting.
jl_fs_copy_tree() {
    local source destination
    source="$1"
    destination="$2"

    [ -d "$source" ] || {
        jl_error "Source directory not found: $source"
        return "$JL_EXIT_VALIDATION"
    }
    jl_fs_assert_mutable_path "$destination" || return $?

    if [ -e "$destination" ]; then
        jl_error "Refusing to overwrite existing destination: $destination"
        return "$JL_EXIT_UNSAFE"
    fi

    mkdir -p "$(dirname "$destination")"
    cp -R "$source" "$destination"
}

# Write stdin to a sibling temporary file and atomically replace the target.
jl_fs_atomic_write() {
    local target temp_file
    target="$1"
    jl_fs_assert_mutable_path "$target" || return $?
    mkdir -p "$(dirname "$target")"

    temp_file="$(jl_mktemp_file_near "$target")" || return $?
    if ! cat > "$temp_file"; then
        rm -f "$temp_file"
        return "$JL_EXIT_GENERAL"
    fi

    if [ -e "$target" ]; then
        chmod "$(jl_stat_mode "$target")" "$temp_file"
    else
        chmod 644 "$temp_file"
    fi

    mv "$temp_file" "$target"
}

# Move a source to a non-existing destination after safety checks.
jl_fs_safe_move() {
    local source destination
    source="$1"
    destination="$2"

    [ -e "$source" ] || {
        jl_error "Source path not found: $source"
        return "$JL_EXIT_VALIDATION"
    }
    jl_fs_assert_mutable_path "$source" || return $?
    jl_fs_assert_mutable_path "$destination" || return $?

    if [ -e "$destination" ]; then
        jl_error "Refusing to overwrite existing destination: $destination"
        return "$JL_EXIT_UNSAFE"
    fi

    mkdir -p "$(dirname "$destination")"
    mv "$source" "$destination"
}

# Return success when two regular files have identical content.
jl_fs_same_bytes() {
    local first second
    first="$1"
    second="$2"
    cmp -s "$first" "$second"
}

# Return success when a directory has no immediate entries.
jl_fs_directory_is_empty() {
    local path
    path="$1"
    [ -d "$path" ] || return 1
    [ -z "$(find "$path" -mindepth 1 -maxdepth 1 -print -quit)" ]
}

# Copy the contents of a source directory into an existing empty destination.
# This is intended for one-time imports during project creation.
# Copy every top-level source entry into an existing destination safely.
jl_fs_copy_directory_contents() {
    local source destination entry
    source="$1"
    destination="$2"

    [ -d "$source" ] || {
        jl_error "Source directory not found: $source"
        return "$JL_EXIT_VALIDATION"
    }
    [ -d "$destination" ] || {
        jl_error "Destination directory not found: $destination"
        return "$JL_EXIT_VALIDATION"
    }
    jl_fs_directory_is_empty "$destination" || {
        jl_error "Destination must be empty before importing files: $destination"
        return "$JL_EXIT_UNSAFE"
    }

    # Include dotfiles without relying on shell-specific glob options.
    find "$source" -mindepth 1 -maxdepth 1 -print |
    while IFS= read -r entry; do
        cp -Rp "$entry" "$destination/"
    done
}

# Return success only for a regular file that is not a symbolic link.
# The ordinary -f test follows symlinks, so v1.1 commands use this stricter
# helper whenever ownership boundaries require no-follow behavior.
jl_fs_is_regular_file_no_symlink() {
    [ -f "$1" ] && [ ! -L "$1" ]
}

# Return success only for a directory that is not itself a symbolic link.
jl_fs_is_directory_no_symlink() {
    [ -d "$1" ] && [ ! -L "$1" ]
}

# Validate a lexical absolute path before canonical resolution. Dot segments,
# repeated separators, and backslashes are rejected so callers do not silently
# reinterpret a user-supplied path.
jl_path_validate_absolute() {
    local absolute_path wrapped
    absolute_path="$1"

    case "$absolute_path" in
        /*) ;;
        *)
            jl_error "Absolute path required: $absolute_path"
            return "$JL_EXIT_VALIDATION"
            ;;
    esac
    case "$absolute_path" in
        *'\'*)
            jl_error "Backslashes are not allowed in absolute paths: $absolute_path"
            return "$JL_EXIT_VALIDATION"
            ;;
    esac

    [ "$absolute_path" = / ] && return 0
    wrapped="$absolute_path/"
    case "$wrapped" in
        *'//'*|*'/./'*|*'/../'*)
            jl_error "Unsafe absolute path segments in: $absolute_path"
            return "$JL_EXIT_VALIDATION"
            ;;
    esac
}

# Reject absolute paths and any empty, dot, or dot-dot path segment. Relative
# paths accepted here use forward slashes so manifest paths remain portable.
jl_path_validate_relative() {
    local relative_path wrapped
    relative_path="$1"

    case "$relative_path" in
        ''|/*|*'\'*)
            jl_error "Unsafe relative path: $relative_path"
            return "$JL_EXIT_VALIDATION"
            ;;
    esac

    wrapped="/$relative_path/"
    case "$wrapped" in
        *'//'*|*'/./'*|*'/../'*)
            jl_error "Unsafe relative path segments in: $relative_path"
            return "$JL_EXIT_VALIDATION"
            ;;
    esac
}

# Resolve a validated relative path beneath one absolute root. This function
# does not require the final path to exist and rejects any lexical escape.
jl_path_resolve_under_root() {
    local root relative_path resolved
    root="$(jl_realpath "$1")" || return $?
    relative_path="$2"
    jl_path_validate_relative "$relative_path" || return $?
    resolved="$(jl_abspath_allow_missing "$root/$relative_path")" || return $?

    case "$resolved" in
        "$root"/*) printf '%s\n' "$resolved" ;;
        *)
            jl_error "Resolved path escapes root '$root': $relative_path"
            return "$JL_EXIT_UNSAFE"
            ;;
    esac
}

# Reject a path when any existing component from root through the destination
# is a symbolic link. The final destination may be missing.
jl_fs_assert_no_symlink_components() {
    local root destination python_command status
    [ ! -L "$1" ] || {
        jl_error "Symlink root is not allowed: $1"
        return "$JL_EXIT_UNSAFE"
    }
    root="$(jl_realpath "$1")" || return $?
    python_command="$(command -v python3 2>/dev/null || true)"
    if [ -z "$python_command" ]; then
        jl_error "Python 3 is required for symlink-safe path validation."
        return "$JL_EXIT_CONFIG"
    fi

    destination="$("$python_command" - "$2" <<'PY_LEXICAL_ABSPATH'
import os
import sys
print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY_LEXICAL_ABSPATH
)" || return $?

    if "$python_command" - "$root" "$destination" <<'PY_NO_SYMLINKS'
import sys
from pathlib import Path

root = Path(sys.argv[1])
destination = Path(sys.argv[2])
try:
    destination.relative_to(root)
except ValueError:
    print(f"Path escapes root: {destination}", file=sys.stderr)
    raise SystemExit(6)

current = root
if current.is_symlink():
    print(f"Symbolic-link path component is not allowed: {current}", file=sys.stderr)
    raise SystemExit(6)
for part in destination.relative_to(root).parts:
    current = current / part
    if current.is_symlink():
        print(f"Symbolic-link path component is not allowed: {current}", file=sys.stderr)
        raise SystemExit(6)
raise SystemExit(0)
PY_NO_SYMLINKS
    then
        return 0
    else
        status=$?
    fi
    case "$status" in
        0) return 0 ;;
        6)
            jl_error "Unsafe symbolic-link path: $destination"
            return "$JL_EXIT_UNSAFE"
            ;;
        *)
            jl_error "Unable to validate path safely: $destination"
            return "$JL_EXIT_GENERAL"
            ;;
    esac
}

# Return success when two paths reside on the same filesystem. Missing final
# components are checked through their nearest existing parent directory.
jl_fs_same_filesystem() {
    local first second first_existing second_existing
    first="$1"
    second="$2"

    # Atomic rename depends on the source and destination parent directories,
    # not on overlay-specific device metadata that a regular file may expose.
    first_existing="$(dirname "$(jl_abspath_allow_missing "$first")")"
    second_existing="$(dirname "$(jl_abspath_allow_missing "$second")")"

    while [ ! -d "$first_existing" ] && [ "$first_existing" != / ]; do
        first_existing="$(dirname "$first_existing")"
    done
    while [ ! -d "$second_existing" ] && [ "$second_existing" != / ]; do
        second_existing="$(dirname "$second_existing")"
    done

    [ "$(jl_stat_device "$first_existing")" = "$(jl_stat_device "$second_existing")" ]
}

# Print the existing immediate child whose name collides case-insensitively
# with a proposed basename. Symlink entries are considered collisions too.
jl_fs_find_case_insensitive_child_collision() {
    local parent proposed python_command
    parent="$1"
    proposed="$2"
    python_command="$(command -v python3 2>/dev/null || true)"
    [ -n "$python_command" ] || return "$JL_EXIT_CONFIG"
    [ -d "$parent" ] || return 1

    "$python_command" - "$parent" "$proposed" <<'PY_CHILD_COLLISION'
import os
import sys

parent = sys.argv[1]
proposed = sys.argv[2].casefold()
for name in os.listdir(parent):
    if name.casefold() == proposed:
        print(os.path.join(parent, name))
        raise SystemExit(0)
raise SystemExit(1)
PY_CHILD_COLLISION
}

# Fail when an immediate filesystem child would collide on a case-insensitive
# platform. No numeric suffix is generated automatically.
jl_fs_assert_no_case_insensitive_child_collision() {
    local parent proposed collision status
    parent="$1"
    proposed="$2"

    if collision="$(jl_fs_find_case_insensitive_child_collision "$parent" "$proposed" 2>/dev/null)"; then
        jl_error "Case-insensitive path collision: $collision"
        return "$JL_EXIT_VALIDATION"
    else
        status=$?
    fi

    # A status of 1 means the search completed and found no collision.
    [ "$status" -eq 1 ] && return 0
    jl_error "Unable to perform case-insensitive collision check: $parent"
    return "$status"
}

# Remove one file, directory, or symlink entry without following symlinks.
# This is suitable only after a caller has explicitly authorized cleanup.
jl_fs_remove_entry_no_follow() {
    local path
    path="$1"
    if [ -L "$path" ] || [ -f "$path" ]; then
        rm -f -- "$path"
    elif [ -d "$path" ]; then
        rm -rf -- "$path"
    elif [ -e "$path" ]; then
        jl_error "Unsupported filesystem entry cannot be removed safely: $path"
        return "$JL_EXIT_UNSAFE"
    fi
}

# Identify content inside the opaque DAW project boundary.
jl_fs_is_daw_project_path() {
    local path
    path="$(jl_abspath_allow_missing "$1")" || return $?
    case "$path" in
        */03_DAW_Project|*/03_DAW_Project/*) return 0 ;;
        *) return 1 ;;
    esac
}

# Reject writes into immutable or opaque user-owned boundaries. Creation
# commands may create the boundary directories themselves, but subsequent
# automation must not manage their contents.
jl_fs_assert_automation_owned_path() {
    local path
    path="$1"
    jl_fs_assert_mutable_path "$path" || return $?
    if jl_fs_is_daw_project_path "$path"; then
        jl_error "Unsafe operation prevented inside opaque 03_DAW_Project: $path"
        return "$JL_EXIT_UNSAFE"
    fi
}
