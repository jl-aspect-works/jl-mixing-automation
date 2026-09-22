#!/usr/bin/env bash
# Studio configuration lookup and default-resolution helpers.
#
# Resolution follows the product rule: explicit value, client default, studio
# default, then built-in fallback.
if [ "${JL_MIXING_CONFIG_LOADED:-0}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi
JL_MIXING_CONFIG_LOADED=1

JL_CONFIG_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$JL_CONFIG_LIB_DIR/common.sh"
# shellcheck source=lib/platform.sh
. "$JL_CONFIG_LIB_DIR/platform.sh"
# shellcheck source=lib/json.sh
. "$JL_CONFIG_LIB_DIR/json.sh"

# Return the configured workspace root or the product default.
jl_config_default_root() {
    printf '%s\n' "${JL_MIXING_ROOT:-$HOME/Music/Mixes}"
}

# Build the studio.json path for a workspace root.
jl_config_file() {
    local studio_root
    studio_root="$1"
    printf '%s/Studio/studio.json\n' "${studio_root%/}"
}

# Verify that a path contains a supported mixing-studio configuration.
jl_config_validate_root() {
    local studio_root config_file
    studio_root="$1"
    config_file="$(jl_config_file "$studio_root")"
    if [ ! -f "$config_file" ]; then
        jl_error "Studio configuration not found: $config_file"
        return "$JL_EXIT_CONFIG"
    fi
    jl_json_require_schema_identity "$config_file" mixing-studio 1
}

# Read a configuration value after validating the studio root.
jl_config_get() {
    local studio_root filter default_value config_file
    studio_root="$1"
    filter="$2"
    default_value="${3:-}"
    config_file="$(jl_config_file "$studio_root")"
    jl_config_validate_root "$studio_root" || return $?
    jl_json_get_optional "$config_file" "$filter" "$default_value"
}

# Walk upward for studio.json, then try the configured default workspace.
jl_config_find_root() {
    local start_path current parent default_root
    start_path="${1:-$PWD}"
    current="$(jl_abspath_allow_missing "$start_path")" || return $?
    [ -d "$current" ] || current="$(dirname "$current")"

    while :; do
        if [ -f "$current/Studio/studio.json" ]; then
            printf '%s\n' "$current"
            return 0
        fi
        parent="$(dirname "$current")"
        [ "$parent" != "$current" ] || break
        current="$parent"
    done

    default_root="$(jl_abspath_allow_missing "$(jl_config_default_root)")"
    if [ -f "$default_root/Studio/studio.json" ]; then
        printf '%s\n' "$default_root"
        return 0
    fi

    return "$JL_EXIT_CONTEXT"
}

# Apply explicit, client, studio, and fallback precedence to one setting.
jl_resolve_value() {
    local explicit_value client_file client_filter studio_file studio_filter fallback_value value
    explicit_value="$1"
    client_file="$2"
    client_filter="$3"
    studio_file="$4"
    studio_filter="$5"
    fallback_value="$6"

    if [ -n "$explicit_value" ]; then
        printf '%s\n' "$explicit_value"
        return 0
    fi

    if [ -n "$client_file" ] && [ -f "$client_file" ]; then
        value="$(jl_json_get_optional "$client_file" "$client_filter" '')"
        if [ -n "$value" ]; then
            printf '%s\n' "$value"
            return 0
        fi
    fi

    if [ -n "$studio_file" ] && [ -f "$studio_file" ]; then
        value="$(jl_json_get_optional "$studio_file" "$studio_filter" '')"
        if [ -n "$value" ]; then
            printf '%s\n' "$value"
            return 0
        fi
    fi

    printf '%s\n' "$fallback_value"
}
