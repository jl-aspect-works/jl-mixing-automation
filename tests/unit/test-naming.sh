#!/usr/bin/env bash
set -eu

# Purpose: Verify stable slugs and filesystem-safe naming conventions.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
. "$ROOT/lib/naming.sh"

# Assert: verify observable behavior rather than internal implementation.
assert_eq "acme-records" "$(jl_slugify 'Acme Records')" "slugify name"
assert_eq "Acme Records" "$(jl_title_from_slug acme-records)" "title from slug"
assert_eq "Bad-Name" "$(jl_sanitize_component ' Bad/Name ')" "sanitize filename component"
assert_eq "Revision_03" "$(jl_revision_name 3)" "revision name"
assert_eq "Acme - Blue Sky" "$(jl_daw_project_name Acme 'Blue Sky')" "DAW project name"
assert_eq "Acme - Blue Sky - Main Mix.wav" "$(jl_deliverable_name Acme 'Blue Sky' 'Main Mix' wav)" "deliverable filename"
assert_eq "WORK Acme - Blue Sky - Car Test.wav" "$(jl_working_print_name 'WORK ' Acme 'Blue Sky' 'Car Test' wav)" "working print filename"
assert_eq "Acme - Blue Sky - Main Mix" "$(jl_expand_naming_pattern '{{ARTIST}} - {{PROJECT_NAME}} - {{DELIVERABLE}}' Acme 'Blue Sky' 'Main Mix')" "pattern expansion"
assert_eq "Smith - Jones Productions" \
    "$(jl_sanitize_folder_name ' Smith / Jones Productions. ')" \
    "readable folder name sanitized"
assert_failure "reserved folder name rejected" jl_sanitize_folder_name CON
assert_failure "empty folder result rejected" jl_sanitize_folder_name '///'
assert_eq "blue-sky-radio-mix" \
    "$(jl_project_id_from_name 'Blue Sky / Radio Mix')" \
    "project ID derived deterministically"
assert_eq "strasse" "$(jl_name_casefold 'STRASSE')" "case folding works"
assert_success "case-insensitive unique values accepted" \
    jl_name_assert_case_insensitive_unique Main Instrumental Stems
assert_failure "case-insensitive duplicate values rejected" \
    jl_name_assert_case_insensitive_unique 'Blue Sky' 'blue sky'
echo "[OK] naming.sh ($TEST_COUNT assertions)"
