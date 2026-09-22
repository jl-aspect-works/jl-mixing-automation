#!/usr/bin/env bash
# Verify install, installed command execution, upgrade, and uninstall behavior.
set -eu

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"
expected_created_with="jl-mixing $(cat "$ROOT/VERSION")"

require_test_command python3
require_test_command jq
python3 -c 'import jsonschema' >/dev/null 2>&1 || {
    if [ "${JL_TEST_STRICT:-0}" = "1" ]; then
        fail "Installation tests require the jsonschema package."
    fi
    echo "[SKIP] Installation tests require jsonschema."
    exit 0
}

temp_root="$(new_test_dir)"
trap 'rm -rf "$temp_root"' EXIT HUP INT TERM
prefix="$temp_root/prefix"
workspace="$temp_root/workspace"
fake_home="$temp_root/home"
mkdir -p "$fake_home"
printf 'export USER_INSTALL_SETTING=1
' > "$fake_home/.bashrc"

HOME="$fake_home" SHELL=/bin/bash JL_MIXING_TEST_SYSTEM_SITE_PACKAGES=1 \
    "$ROOT/install.sh" --prefix "$prefix" >/dev/null
assert_file_exists "$prefix/share/jl-mixing/VERSION"
assert_file_exists "$prefix/share/jl-mixing/API_VERSION"
assert_file_exists "$prefix/share/jl-mixing/CHANGELOG.md"
assert_file_exists "$prefix/share/jl-mixing/.venv/bin/python"
assert_file_exists "$prefix/bin/jl-mixing"
assert_file_exists "$prefix/bin/new-studio"
assert_file_exists "$prefix/bin/new-client"
assert_file_exists "$prefix/bin/jl-mixing-shell-integration"
assert_file_exists "$prefix/bin/jl-mixing-uninstall"
assert_path_not_exists "$prefix/bin/complete-project"
assert_file_exists "$prefix/share/jl-mixing/install-state.json"
assert_json_eq "true" "$prefix/share/jl-mixing/install-state.json"     '.shell_integration.enabled' "install state records shell integration"
assert_contains "$(cat "$fake_home/.bashrc")"     "# >>> JL Mixing managed configuration >>>"     "installer adds one managed shell block"
assert_file_exists "$prefix/share/jl-mixing/tools/project-state.py"
assert_file_exists "$prefix/share/jl-mixing/tools/import-project-source.py"
assert_file_exists "$prefix/share/jl-mixing/tools/import-revision-source.py"
assert_file_exists "$prefix/share/jl-mixing/tools/build-delivery.py"
assert_file_exists "$prefix/share/jl-mixing/tools/manage-shell-config.py"
assert_file_exists "$prefix/share/jl-mixing/api/schemas/v1.0/system-info.schema.json"
assert_file_exists "$prefix/share/jl-mixing/api/examples/v1.0/success/system-info.json"
assert_file_exists "$prefix/share/jl-mixing/schemas/client-profile-snapshot.schema.json"
assert_file_exists "$prefix/share/jl-mixing/templates/Intake_Report.md"
assert_file_exists "$prefix/share/jl-mixing/templates/Revision_Notes.md"
assert_success "installed help works" "$prefix/bin/new-studio" --help
api_info="$temp_root/system-info.json"
"$prefix/bin/jl-mixing" system-info --json > "$api_info"
assert_json_eq "1.0" "$api_info" ".api_version" "installed dispatcher reports API version"
assert_json_eq "$(cat "$ROOT/VERSION")" "$api_info" ".application.version" \
    "installed dispatcher reports application version"
assert_json_eq "true" "$api_info" '[.capabilities[] | select(. == "system.info")] | length == 1' \
    "installed dispatcher advertises discovery capability"
assert_json_eq "true" "$api_info" '[.capabilities[] | select(. == "client.create")] | length == 1' \
    "installed dispatcher advertises client.create capability"
assert_json_eq "$prefix/share/jl-mixing/api/schemas/v1.0" "$api_info" \
    ".schemas.installed_path" "installed dispatcher reports bundled schemas"

PATH="$prefix/bin:$PATH" new-studio --root "$workspace" >/dev/null
assert_file_exists "$workspace/Studio/studio.json"
assert_json_eq "1.1.0" "$workspace/Studio/studio.json" \
    '.metadata.schema_version' "installed new-studio creates v1.1 schema"
assert_json_eq "$expected_created_with" "$workspace/Studio/studio.json" \
    '.metadata.created_with' "installed new-studio records application release"
assert_path_not_exists "$workspace/DAWs"

JL_MIXING_ROOT="$workspace" PATH="$prefix/bin:$PATH" \
    new-client installed-client --name "Installed Client" >/dev/null
installed_client="$workspace/Clients/Installed Client/client.json"
assert_file_exists "$installed_client"
assert_json_eq "1.1.0" "$installed_client" '.metadata.schema_version' \
    "installed new-client creates v1.1 schema"
assert_json_eq "$expected_created_with" "$installed_client" '.metadata.created_with' \
    "installed new-client records application release"
assert_dir_exists "$workspace/Clients/Installed Client/Projects"
assert_path_not_exists "$workspace/Clients/Installed Client/Projects/Active"

JL_MIXING_ROOT="$workspace" PATH="$prefix/bin:$PATH" \
    new-mix --client installed-client --project "Installed Project" \
    --artist "Installed Artist" >/dev/null
installed_project="$workspace/Clients/Installed Client/Projects/Installed Project"
installed_manifest="$installed_project/00_Admin/project-manifest.json"
assert_file_exists "$installed_manifest"
assert_file_exists "$installed_project/00_Admin/client-profile-snapshot.json"
assert_json_eq "1.1.0" "$installed_manifest" '.metadata.schema_version' \
    "installed new-mix creates v1.1 schema"
assert_json_eq "$expected_created_with" "$installed_manifest" '.metadata.created_with' \
    "installed new-mix records application release"
assert_dir_exists "$installed_project/03_DAW_Project"
assert_path_not_exists "$installed_project/03_DAW_Project/Project"
assert_path_not_exists "$installed_project/05_Final_Delivery/delivery-manifest.json"
assert_file_exists "$installed_project/04_Revisions/Revision_01/Revision_Notes.md"
assert_json_eq "1" "$installed_manifest" '.state.current_revision' \
    "installed new-mix creates Revision 1"

printf 'installed notes\n' > "$installed_project/01_Client_Files/Original_Delivery/Notes.txt"
PATH="$prefix/bin:$PATH" validate-intake --project "$installed_project" >/dev/null
assert_contains "$(cat "$installed_project/00_Admin/Intake_Report.md")" \
    "## Unsupported or Non-Audio Files" \
    "installed validate-intake updates the v1.1 managed report"

assert_path_not_exists "$installed_project/04_Revisions/Revision_01/Prints"
printf 'installed main mix\n' > \
    "$installed_project/04_Revisions/Revision_01/Installed Main Mix.wav"
PATH="$prefix/bin:$PATH" approve-mix --project "$installed_project" \
    --approved-by Client --date 2030-01-01T12:00:00Z >/dev/null
assert_json_eq "1" "$installed_manifest" '.state.approved_revision' \
    "installed approve-mix records v1.1 approval"
PATH="$prefix/bin:$PATH" create-delivery --project "$installed_project" >/dev/null
assert_file_exists "$installed_project/05_Final_Delivery/delivery-manifest.json"
assert_json_eq "$expected_created_with" \
    "$installed_project/05_Final_Delivery/delivery-manifest.json" \
    '.metadata.created_with' "installed delivery records application release"
assert_json_eq "1" "$installed_manifest" '.state.delivered_revision' \
    "installed create-delivery records delivered revision"

# A sentinel in the application directory must disappear during upgrade, while
# the independent studio workspace remains untouched.
printf 'old application file\n' > "$prefix/share/jl-mixing/obsolete-sentinel"
HOME="$fake_home" SHELL=/bin/bash JL_MIXING_TEST_SYSTEM_SITE_PACKAGES=1 \
    "$ROOT/install.sh" --prefix "$prefix" >/dev/null
assert_path_not_exists "$prefix/share/jl-mixing/obsolete-sentinel"
assert_file_exists "$workspace/Studio/studio.json"
assert_eq "1" "$(grep -c '^# >>> JL Mixing managed configuration >>>$' "$fake_home/.bashrc")"     "reinstall keeps one managed shell block"

HOME="$fake_home" SHELL=/bin/bash "$prefix/bin/jl-mixing-uninstall" >/dev/null
assert_path_not_exists "$prefix/share/jl-mixing"
assert_path_not_exists "$prefix/bin/jl-mixing"
assert_path_not_exists "$prefix/bin/new-studio"
assert_path_not_exists "$prefix/bin/jl-mixing-shell-integration"
assert_file_exists "$workspace/Studio/studio.json"
assert_eq "export USER_INSTALL_SETTING=1" "$(cat "$fake_home/.bashrc")"     "uninstall preserves user shell content"

echo "[OK] installation lifecycle ($TEST_COUNT assertions)"
