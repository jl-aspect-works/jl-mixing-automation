#!/usr/bin/env bash
# Common helpers shared by every JL Mixing Automation command.
# Compatible with the Bash 3.2 version included with macOS.
#
# This module defines the public exit-code contract, logging, prompts, UUID and
# timestamp generation, and small string helpers used across the application.
if [ "${JL_MIXING_COMMON_LOADED:-0}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi
JL_MIXING_COMMON_LOADED=1

# Standard JL Mixing Automation exit codes.
#
# These constants form part of the public shared-library API and are consumed
# by commands that source this file. ShellCheck analyzes this file separately.
# shellcheck disable=SC2034
readonly \
    JL_EXIT_GENERAL=1 \
    JL_EXIT_ARGUMENTS=2 \
    JL_EXIT_CONFIG=3 \
    JL_EXIT_CONTEXT=4 \
    JL_EXIT_VALIDATION=5 \
    JL_EXIT_UNSAFE=6

: "${JL_MIXING_LOG_LEVEL:=info}"

# Return success when the named executable can be resolved through PATH.
jl_command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Map a textual log level to a numeric threshold for comparison.
jl_log_level_number() {
    local level
    case "$1" in
        debug) printf '%s\n' 10 ;;
        info)  printf '%s\n' 20 ;;
        warn)  printf '%s\n' 30 ;;
        error) printf '%s\n' 40 ;;
        *)     printf '%s\n' 20 ;;
    esac
}

# Write a message to stderr when its level meets the configured threshold.
jl_log() {
    local level configured requested label
    level="$1"
    shift

    configured="$(jl_log_level_number "$JL_MIXING_LOG_LEVEL")"
    requested="$(jl_log_level_number "$level")"
    [ "$requested" -ge "$configured" ] || return 0

    label="$(printf '%s' "$level" | tr '[:lower:]' '[:upper:]')"
    printf '[%s] %s\n' "$label" "$*" >&2
}

jl_debug() { jl_log debug "$@"; }
jl_info()  { jl_log info "$@"; }
jl_warn()  { jl_log warn "$@"; }
jl_error() { jl_log error "$@"; }

# Report an error and return the requested application exit code.
jl_die() {
    local message code
    message="$1"
    code="${2:-$JL_EXIT_GENERAL}"
    jl_error "$message"
    return "$code"
}

# Verify that a required external command is installed and explain how to recover.
jl_require_command() {
    local command_name install_hint
    command_name="$1"
    install_hint="${2:-Install '$command_name' and try again.}"

    if ! jl_command_exists "$command_name"; then
        jl_error "Required command not found: $command_name"
        jl_error "$install_hint"
        return "$JL_EXIT_CONFIG"
    fi
}

# Reject an empty required value with a consistent argument error.
jl_assert_nonempty() {
    local value label
    value="$1"
    label="${2:-value}"
    if [ -z "$value" ]; then
        jl_error "$label must not be empty."
        return "$JL_EXIT_ARGUMENTS"
    fi
}

# Remove leading and trailing POSIX whitespace without Bash extglob.
jl_trim() {
    local value
    # sed is used instead of Bash extglob so this remains portable to Bash 3.2.
    printf '%s' "$1" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

# Recognize the accepted case-insensitive true values.
jl_is_truthy() {
    local value
    case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
        1|true|yes|y|on) return 0 ;;
        *) return 1 ;;
    esac
}

# Join positional arguments using the supplied delimiter.
jl_join_by() {
    local delimiter result separator item
    delimiter="$1"
    shift
    result=""
    separator=""
    for item in "$@"; do
        result="${result}${separator}${item}"
        separator="$delimiter"
    done
    printf '%s\n' "$result"
}

# Return a stable UTC ISO-8601 timestamp.
jl_now_iso8601() {
    # UTC is stable across macOS and Linux and satisfies ISO-8601 date-time.
    date -u '+%Y-%m-%dT%H:%M:%SZ'
}

# Generate a lowercase UUID using uuidgen, with Python as a portable fallback.
jl_uuid() {
    if jl_command_exists uuidgen; then
        uuidgen | tr '[:upper:]' '[:lower:]'
        return 0
    fi

    if jl_command_exists python3; then
        python3 - <<'PY_UUID'
# uuid.uuid4 provides the same random UUID semantics as the uuidgen path.
import uuid
print(uuid.uuid4())
PY_UUID
        return 0
    fi

    jl_error "Cannot generate a UUID: neither uuidgen nor python3 is available."
    return "$JL_EXIT_CONFIG"
}

# Read a line from the user and apply a default when the response is empty.
jl_prompt() {
    local prompt_text default_value response
    prompt_text="$1"
    default_value="${2:-}"

    if [ -n "$default_value" ]; then
        printf '%s [%s]: ' "$prompt_text" "$default_value" >&2
    else
        printf '%s: ' "$prompt_text" >&2
    fi

    IFS= read -r response || response=""
    if [ -z "$response" ]; then
        response="$default_value"
    fi
    printf '%s\n' "$response"
}

# Ask a yes/no question and return success only for an affirmative response.
jl_confirm() {
    local prompt_text default_answer suffix response
    prompt_text="$1"
    default_answer="${2:-no}"

    if [ "$default_answer" = "yes" ]; then
        suffix='[Y/n]'
    else
        suffix='[y/N]'
    fi

    printf '%s %s ' "$prompt_text" "$suffix" >&2
    IFS= read -r response || response=""
    response="$(printf '%s' "$response" | tr '[:upper:]' '[:lower:]')"

    if [ -z "$response" ]; then
        [ "$default_answer" = "yes" ]
        return
    fi

    case "$response" in
        y|yes) return 0 ;;
        *) return 1 ;;
    esac
}
