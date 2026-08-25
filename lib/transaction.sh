#!/usr/bin/env bash
# Rollback-capable filesystem transactions for JL Mixing v1.1 commands.
#
# Commands build complete proposed results in sibling staging paths, validate
# them, and only then call these helpers. Rename operations therefore remain on
# one filesystem and can be reversed when a later coordinated step fails.
if [ "${JL_MIXING_TRANSACTION_LOADED:-0}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi
JL_MIXING_TRANSACTION_LOADED=1

JL_TRANSACTION_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$JL_TRANSACTION_LIB_DIR/common.sh"
# shellcheck source=lib/platform.sh
. "$JL_TRANSACTION_LIB_DIR/platform.sh"
# shellcheck source=lib/filesystem.sh
. "$JL_TRANSACTION_LIB_DIR/filesystem.sh"

# Test-only failure injection. A comma-separated JL_MIXING_FAIL_AT value may
# name one or more points. Production callers leave the variable unset.
jl_txn_fail_if_requested() {
    local point configured item old_ifs
    point="$1"
    configured="${JL_MIXING_FAIL_AT:-}"
    [ -n "$configured" ] || return 0

    old_ifs="$IFS"
    IFS=','
    # shellcheck disable=SC2086
    set -- $configured
    IFS="$old_ifs"
    for item in "$@"; do
        if [ "$(jl_trim "$item")" = "$point" ]; then
            jl_error "Injected transaction failure at: $point"
            return "$JL_EXIT_GENERAL"
        fi
    done
}

# Create a hidden staging directory beside the eventual destination.
jl_txn_stage_directory_near() {
    local destination parent
    destination="$1"
    parent="$(dirname "$destination")"

    [ -d "$parent" ] || {
        jl_error "Transaction parent directory not found: $parent"
        return "$JL_EXIT_CONTEXT"
    }
    [ ! -L "$parent" ] || {
        jl_error "Transaction parent must not be a symbolic link: $parent"
        return "$JL_EXIT_UNSAFE"
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
    mv "$source" "$container/original" || {
        rmdir "$container" 2>/dev/null || true
        jl_error "Unable to back up transaction target: $source"
        return "$JL_EXIT_GENERAL"
    }
    printf '%s\n' "$container"
}

# Copy an existing regular file into a backup container while leaving the
# authoritative path in place until the staged file atomically replaces it.
# This avoids a transient missing-manifest window during file-only and
# coordinated directory/file transactions.
jl_txn_backup_existing_file() {
    local source container
    source="$1"
    if [ ! -e "$source" ] && [ ! -L "$source" ]; then
        printf '\n'
        return 0
    fi
    jl_fs_is_regular_file_no_symlink "$source" || {
        jl_error "Transaction file target is missing or unsafe: $source"
        return "$JL_EXIT_UNSAFE"
    }

    container="$(jl_txn_backup_container_near "$source")" || return $?
    cp -p "$source" "$container/original" || {
        jl_fs_remove_entry_no_follow "$container" 2>/dev/null || true
        jl_error "Unable to back up transaction file: $source"
        return "$JL_EXIT_GENERAL"
    }
    printf '%s\n' "$container"
}

# Remove a completed backup container without following a symlink that might
# have replaced it unexpectedly.
jl_txn_discard_backup() {
    local container
    container="$1"
    [ -n "$container" ] || return 0
    if [ -L "$container" ] || [ ! -d "$container" ]; then
        jl_error "Transaction backup container is missing or unsafe: $container"
        return "$JL_EXIT_UNSAFE"
    fi
    jl_fs_remove_entry_no_follow "$container"
}

# Restore one backup, removing only the replacement entry created by the active
# transaction. The backup container itself is never followed when it is a
# symlink.
jl_txn_restore_backup() {
    local container destination original
    container="$1"
    destination="$2"

    if [ -e "$destination" ] || [ -L "$destination" ]; then
        jl_fs_remove_entry_no_follow "$destination" || return $?
    fi
    if [ -n "$container" ]; then
        if [ -L "$container" ] || [ ! -d "$container" ]; then
            jl_error "Transaction backup container is missing or unsafe: $container"
            return "$JL_EXIT_UNSAFE"
        fi
        original="$container/original"
        if [ ! -e "$original" ] && [ ! -L "$original" ]; then
            jl_error "Transaction backup entry is missing: $original"
            return "$JL_EXIT_GENERAL"
        fi
        mv "$original" "$destination" || {
            jl_error "Unable to restore transaction backup: $destination"
            return "$JL_EXIT_GENERAL"
        }
        rmdir "$container" || {
            jl_error "Unable to remove restored backup container: $container"
            return "$JL_EXIT_GENERAL"
        }
    fi
}

# Commit a new staged directory to a destination that must not already exist.
jl_txn_commit_new_directory() {
    local staged_directory destination status
    staged_directory="$1"
    destination="$2"

    jl_fs_is_directory_no_symlink "$staged_directory" || {
        jl_error "Staged directory is missing or unsafe: $staged_directory"
        return "$JL_EXIT_VALIDATION"
    }
    if [ -e "$destination" ] || [ -L "$destination" ]; then
        jl_error "Transaction destination already exists: $destination"
        return "$JL_EXIT_UNSAFE"
    fi
    jl_fs_same_filesystem "$staged_directory" "$(dirname "$destination")" || {
        jl_error "Staging and destination are on different filesystems."
        return "$JL_EXIT_UNSAFE"
    }

    jl_txn_fail_if_requested before-directory-commit || return $?
    mv "$staged_directory" "$destination" || {
        jl_error "Unable to commit staged directory: $destination"
        return "$JL_EXIT_GENERAL"
    }
    if jl_txn_fail_if_requested after-directory-commit; then
        return 0
    else
        status=$?
    fi

    jl_fs_remove_entry_no_follow "$destination" || {
        jl_error "New-directory commit failed and cleanup was incomplete: $destination"
        return "$JL_EXIT_GENERAL"
    }
    return "$status"
}

# Replace a directory as one rollback-capable transaction. Existing contents
# may be replaced only after the calling command has obtained explicit user
# authorization and completed all staging validation.
jl_txn_replace_directory() {
    local staged_directory destination backup status rollback_status
    staged_directory="$1"
    destination="$2"
    backup=""

    jl_fs_is_directory_no_symlink "$staged_directory" || {
        jl_error "Staged directory is missing or unsafe: $staged_directory"
        return "$JL_EXIT_VALIDATION"
    }
    jl_fs_same_filesystem "$staged_directory" "$(dirname "$destination")" || {
        jl_error "Staging and destination are on different filesystems."
        return "$JL_EXIT_UNSAFE"
    }

    backup="$(jl_txn_backup_existing "$destination")" || return $?
    status=0
    jl_txn_fail_if_requested after-directory-backup || status=$?
    if [ "$status" -eq 0 ]; then
        mv "$staged_directory" "$destination" || status=$?
    fi
    if [ "$status" -eq 0 ]; then
        jl_txn_fail_if_requested after-directory-replacement || status=$?
    fi

    if [ "$status" -eq 0 ]; then
        [ -z "$backup" ] || jl_txn_discard_backup "$backup"
        return 0
    fi

    rollback_status=0
    jl_txn_restore_backup "$backup" "$destination" || rollback_status=$?
    if [ "$rollback_status" -ne 0 ]; then
        jl_error "Directory replacement failed and rollback was incomplete: $destination"
        return "$JL_EXIT_GENERAL"
    fi
    return "$status"
}

# Commit a staged directory and staged manifest as one coordinated operation.
# The manifest staging file must be a sibling of its final path so its rename is
# atomic. Both prior targets are restored if either commit or verification hook
# fails.
jl_txn_commit_directory_and_file() {
    local staged_directory destination_directory staged_file destination_file
    local directory_backup file_backup status rollback_failed
    staged_directory="$1"
    destination_directory="$2"
    staged_file="$3"
    destination_file="$4"
    shift 4
    directory_backup=""
    file_backup=""

    jl_fs_is_directory_no_symlink "$staged_directory" || {
        jl_error "Staged directory is missing or unsafe: $staged_directory"
        return "$JL_EXIT_VALIDATION"
    }
    jl_fs_is_regular_file_no_symlink "$staged_file" || {
        jl_error "Staged manifest is missing or unsafe: $staged_file"
        return "$JL_EXIT_VALIDATION"
    }
    jl_fs_same_filesystem "$staged_directory" "$(dirname "$destination_directory")" || {
        jl_error "Directory staging is on a different filesystem."
        return "$JL_EXIT_UNSAFE"
    }
    jl_fs_same_filesystem "$staged_file" "$(dirname "$destination_file")" || {
        jl_error "Manifest staging is on a different filesystem."
        return "$JL_EXIT_UNSAFE"
    }

    directory_backup="$(jl_txn_backup_existing "$destination_directory")" || return $?
    file_backup="$(jl_txn_backup_existing_file "$destination_file")" || {
        jl_txn_restore_backup "$directory_backup" "$destination_directory" || true
        return "$JL_EXIT_GENERAL"
    }

    status=0
    jl_txn_fail_if_requested after-coordinated-backup || status=$?
    if [ "$status" -eq 0 ]; then
        mv "$staged_directory" "$destination_directory" || status=$?
    fi
    if [ "$status" -eq 0 ]; then
        jl_txn_fail_if_requested after-coordinated-directory || status=$?
    fi
    if [ "$status" -eq 0 ]; then
        mv "$staged_file" "$destination_file" || status=$?
    fi
    if [ "$status" -eq 0 ]; then
        jl_txn_fail_if_requested after-coordinated-file || status=$?
    fi
    if [ "$status" -eq 0 ] && [ "$#" -gt 0 ]; then
        "$@" || status=$?
    fi

    if [ "$status" -eq 0 ]; then
        [ -z "$directory_backup" ] || jl_txn_discard_backup "$directory_backup"
        [ -z "$file_backup" ] || jl_txn_discard_backup "$file_backup"
        return 0
    fi

    rollback_failed=0
    jl_txn_restore_backup "$file_backup" "$destination_file" || rollback_failed=1
    jl_txn_restore_backup "$directory_backup" "$destination_directory" || rollback_failed=1
    if [ "$rollback_failed" -ne 0 ]; then
        jl_error "Coordinated transaction failed and rollback was incomplete."
        return "$JL_EXIT_GENERAL"
    fi
    return "$status"
}

# Atomically replace one staged file and retain the prior file until an optional
# verifier succeeds. The staged file must be a sibling of the destination so
# rename remains atomic.
jl_txn_replace_file() {
    local staged_file destination_file backup status rollback_status
    staged_file="$1"
    destination_file="$2"
    shift 2
    backup=""

    jl_fs_is_regular_file_no_symlink "$staged_file" || {
        jl_error "Staged file is missing or unsafe: $staged_file"
        return "$JL_EXIT_VALIDATION"
    }
    jl_fs_same_filesystem "$staged_file" "$(dirname "$destination_file")" || {
        jl_error "File staging is on a different filesystem."
        return "$JL_EXIT_UNSAFE"
    }

    backup="$(jl_txn_backup_existing_file "$destination_file")" || return $?
    status=0
    jl_txn_fail_if_requested after-file-backup || status=$?
    if [ "$status" -eq 0 ]; then
        mv "$staged_file" "$destination_file" || status=$?
    fi
    if [ "$status" -eq 0 ]; then
        jl_txn_fail_if_requested after-file-replacement || status=$?
    fi
    if [ "$status" -eq 0 ] && [ "$#" -gt 0 ]; then
        "$@" || status=$?
    fi

    if [ "$status" -eq 0 ]; then
        [ -z "$backup" ] || jl_txn_discard_backup "$backup"
        return 0
    fi

    rollback_status=0
    jl_txn_restore_backup "$backup" "$destination_file" || rollback_status=$?
    if [ "$rollback_status" -ne 0 ]; then
        jl_error "File replacement failed and rollback was incomplete: $destination_file"
        return "$JL_EXIT_GENERAL"
    fi
    return "$status"
}
