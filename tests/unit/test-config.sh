#!/usr/bin/env bash
set -eu

# Purpose: Verify v1.1 studio discovery and explicit/client/studio/fallback precedence.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
require_test_command jq
. "$ROOT/lib/config.sh"

tmp="$(new_test_dir)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/Studio" "$tmp/Clients/Acme"
jq --arg root "$tmp" '.root_path=$root' "$ROOT/examples/studio.json" > "$tmp/Studio/studio.json"
cp "$ROOT/examples/client.json" "$tmp/Clients/Acme/client.json"

default_root="$(HOME="$tmp/home" JL_MIXING_ROOT='' jl_config_default_root)"
assert_eq "$tmp/home/Music/Mixes" "$default_root" "default workspace root"
assert_eq "$tmp/Studio/studio.json" "$(jl_config_file "$tmp")" "config path"
assert_success "valid studio root" jl_config_validate_root "$tmp"
assert_eq "Jake" "$(jl_config_get "$tmp" '.defaults.mix_engineer')" "config value"
assert_eq "$tmp" "$(jl_config_find_root "$tmp/Clients/Acme")" "find studio root upward"
resolved="$(jl_resolve_value '' "$tmp/Clients/Acme/client.json" '.defaults.audio.sample_rate' "$tmp/Studio/studio.json" '.defaults.audio.sample_rate' 44100)"
assert_eq "48000" "$resolved" "client value wins resolution"
resolved="$(jl_resolve_value 96000 "$tmp/Clients/Acme/client.json" '.defaults.audio.sample_rate' "$tmp/Studio/studio.json" '.defaults.audio.sample_rate' 44100)"
assert_eq "96000" "$resolved" "explicit value wins resolution"
echo "[OK] config.sh ($TEST_COUNT assertions)"
