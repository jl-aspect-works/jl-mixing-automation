#!/usr/bin/env bash
# Transaction helpers for rollback-safe filesystem changes.
# shellcheck shell=bash

JL_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$JL_LIB_DIR/common.sh"
# shellcheck source=lib/platform.sh
source "$JL_LIB_DIR/platform.sh"

jl_txn_fail_requested() {
    local point configured item
    point="$1"
    configured="${JL_MIXING_FAIL_AT:-}"
    [ -n "$configured" ] || return 1
    IFS=',' read -r -a _jl_txn_fail_points <<< "$configured"
    for item in "${_jl_txn_fail_points[@]}"; do
        item="${item#"${item%%[![:space:]]*}"}"
        item="${item%"${item##*[![:space:]]}"}"
        [ "$item" = "$point" ] && return 0
    done
    return 1
}

jl_txn_injected_failure() {
    local point
    point="$1"
    jl_error "Injected transaction failure at: $point"
    return "$JL_EXIT_GENERAL"
}

jl_txn_remove_path() {
    local path
    path="$1"
    if [ -L "$path" ] || [ -f "$path" ]; then
        rm -f "$path"
    elif [ -d "$path" ]; then
        rm -rf "$path"
    fi
}

# Create a unique hidden stage directory beside a destination. The stage must
# stay on the same filesystem as the final destination so rename remains the
# commit primitive.
jl_txn_stage_dir_near() {
    local destination parent
    destination="$1"
    parent="$(dirname "$destination")"
    [ -d "$parent" ] || {
        jl_error "Transaction parent is missing: $parent"
        return "$JL_EXIT_GENERAL"
    }

    jl_mktemp_dir_near "$destination.stage"
}

# Create a unique hidden backup container beside a destination. The original
# entry is moved to the fixed child name ``original``. Keeping the container in
# place avoids races and ambiguous ``mv`` behavior between files and
# directories while a transaction is active.
jl_txn_backup_container_near() {
    local destination
    destination="$1"
    jl_mktemp_dir_near "$destination.backup"
}

# Move an existing entry into a unique sibling backup container. If the source
# does not exist, print an empty line so callers can use one rollback flow.
jl_txn_backup_existing() {
    local source container
    source="$1"
    if [ ! -e "$source" ] && [ ! -L "$source" ]; then
        printf '\n'
        return 0
    fi

    container="$(jl_txn_backup_container_near "$source")" || return $?
    if ! mv "$source" "$container/original"; then
        rmdir "$container" 2>/dev/null || true
        return "$JL_EXIT_GENERAL"
    fi
    printf '%s\n' "$container"
}

jl_txn_restore_backup() {
    local destination container
    destination="$1"
    container="$2"
    [ -n "$container" ] || return 0
    [ -e "$container/original" ] || [ -L "$container/original" ] || return 0

    jl_txn_remove_path "$destination"
    mv "$container/original" "$destination"
    rmdir "$container" 2>/dev/null || true
}

jl_txn_discard_backup() {
    local container
    container="$1"
    [ -n "$container" ] || return 0
    jl_txn_remove_path "$container"
}

# Atomically commit a staged directory to a destination that must not exist.
# Failure injection contracts are preserved for the Python and shell surfaces.
jl_txn_commit_new_directory() {
    local stage destination committed
    stage="$1"
    destination="$2"
    committed=0

    [ -d "$stage" ] && [ ! -L "$stage" ] || {
        jl_error "Staged directory is missing or unsafe: $stage"
        return "$JL_EXIT_GENERAL"
    }
    if [ -e "$destination" ] || [ -L "$destination" ]; then
        jl_error "Transaction destination already exists: $destination"
        return "$JL_EXIT_GENERAL"
    fi
    if jl_txn_fail_requested "before-directory-commit"; then
        jl_txn_injected_failure "before-directory-commit"
        return $?
    fi

    if ! mv "$stage" "$destination"; then
        jl_error "Could not commit staged directory to: $destination"
        return "$JL_EXIT_GENERAL"
    fi
    committed=1

    if jl_txn_fail_requested "after-directory-commit"; then
        jl_txn_injected_failure "after-directory-commit" || true
        if [ "$committed" -eq 1 ]; then
            jl_txn_remove_path "$destination"
        fi
        return "$JL_EXIT_GENERAL"
    fi
}

# Replace one file atomically while preserving rollback hooks.
jl_txn_atomic_write_bytes() {
    local target source temp backup_container replaced
    target="$1"
    source="$2"
    temp=""
    backup_container=""
    replaced=0

    mkdir -p "$(dirname "$target")"
    if [ -L "$target" ] || { [ -e "$target" ] && [ ! -f "$target" ]; }; then
        jl_error "Transaction file target is missing or unsafe: $target"
        return "$JL_EXIT_GENERAL"
    fi

    temp="$(jl_mktemp_file_near "$target")" || return $?
    if ! cat "$source" > "$temp"; then
        rm -f "$temp"
        return "$JL_EXIT_GENERAL"
    fi

    if jl_txn_fail_requested "after-file-backup"; then
        rm -f "$temp"
        jl_txn_injected_failure "after-file-backup"
        return $?
    fi

    if [ -e "$target" ]; then
        backup_container="$(jl_txn_backup_existing "$target")" || {
            rm -f "$temp"
            return "$JL_EXIT_GENERAL"
        }
    fi

    if ! mv "$temp" "$target"; then
        jl_txn_restore_backup "$target" "$backup_container"
        rm -f "$temp"
        return "$JL_EXIT_GENERAL"
    fi
    replaced=1

    if jl_txn_fail_requested "after-file-replacement"; then
        jl_txn_injected_failure "after-file-replacement" || true
        if [ "$replaced" -eq 1 ]; then
            jl_txn_remove_path "$target"
            jl_txn_restore_backup "$target" "$backup_container"
        fi
        return "$JL_EXIT_GENERAL"
    fi

    jl_txn_discard_backup "$backup_container"
}
