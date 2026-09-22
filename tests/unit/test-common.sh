#!/usr/bin/env bash
set -eu

# Purpose: Verify common string, truth-value, timestamp, UUID, and argument helpers.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
. "$ROOT/lib/common.sh"

# Assert: verify observable behavior rather than internal implementation.
assert_eq "hello world" "$(jl_trim '  hello world  ')" "trim whitespace"
assert_success "truthy yes" jl_is_truthy yes
assert_failure "false is not truthy" jl_is_truthy false
assert_eq "a,b,c" "$(jl_join_by , a b c)" "join values"
assert_contains "$(jl_now_iso8601)" "T" "ISO timestamp contains T"
uuid="$(jl_uuid)"
assert_contains "$uuid" "-" "UUID is generated"
assert_failure "empty assertion fails" jl_assert_nonempty "" "test value"
echo "[OK] common.sh ($TEST_COUNT assertions)"
