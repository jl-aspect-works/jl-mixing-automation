#!/usr/bin/env bash
set -eu

# Purpose: Prevent removed lifecycle/schema/template artifacts from returning and
# keep release identity/API compatibility checks aligned with the active release.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
. "$ROOT/tests/test-helper.sh"

assert_path_not_exists "$ROOT/bin/complete-project"
assert_path_not_exists "$ROOT/tests/integration/test-complete-project.sh"
assert_path_not_exists "$ROOT/schemas/legacy"
assert_path_not_exists "$ROOT/templates/project"
assert_path_not_exists "$ROOT/templates/delivery"
assert_path_not_exists "$ROOT/templates/revision"

commands="$(find "$ROOT/bin" -maxdepth 1 -type f -perm -111 -exec basename {} \; | LC_ALL=C sort)"
expected='approve-mix
create-delivery
jl-mixing
jl-mixing-shell-integration
new-client
new-mix
new-revision
new-studio
validate-intake'
assert_eq "$expected" "$commands" "public runtime command set"

for file in "$ROOT/README.md" "$ROOT/packaging/RELEASE_README.md" \
    "$ROOT/docs/USER_GUIDE.md" "$ROOT/docs/SCRIPT_REFERENCE.md" \
    "$ROOT/docs/INSTALLATION_GUIDE.md"; do
    assert_failure "active documentation omits old workspace root: $(basename "$file")" \
        grep -q 'Music/JL Mixing' "$file"
done

assert_file_exists "$ROOT/API_VERSION"
assert_file_exists "$ROOT/api/schemas/v1.0/system-info.schema.json"
assert_file_exists "$ROOT/api/schemas/v1.0/operations/client-create.schema.json"
assert_file_exists "$ROOT/api/schemas/v1.0/operations/project-create.schema.json"
assert_file_exists "$ROOT/api/schemas/v1.0/operations/revision-create.schema.json"
assert_file_exists "$ROOT/api/schemas/v1.0/operations/intake-validate.schema.json"
assert_file_exists "$ROOT/api/schemas/v1.0/operations/revision-approve.schema.json"
assert_file_exists "$ROOT/api/schemas/v1.0/operations/delivery-create.schema.json"
assert_file_exists "$ROOT/api/examples/v1.0/success/system-info.json"
assert_file_exists "$ROOT/api/examples/v1.0/success/client-create.json"
assert_file_exists "$ROOT/api/examples/v1.0/success/project-create.json"
assert_file_exists "$ROOT/api/examples/v1.0/success/revision-create.json"
assert_file_exists "$ROOT/api/examples/v1.0/planned/revision-create.json"
assert_file_exists "$ROOT/api/examples/v1.0/success/intake-validate.json"
assert_file_exists "$ROOT/api/examples/v1.0/planned/intake-validate.json"
assert_file_exists "$ROOT/api/examples/v1.0/blocked/intake-validate.json"
assert_file_exists "$ROOT/api/examples/v1.0/error/intake-validate.json"
assert_file_exists "$ROOT/api/examples/v1.0/success/revision-approve.json"
assert_file_exists "$ROOT/api/examples/v1.0/planned/revision-approve.json"
assert_file_exists "$ROOT/api/examples/v1.0/blocked/revision-approve.json"
assert_file_exists "$ROOT/api/examples/v1.0/success/delivery-create.json"
assert_file_exists "$ROOT/api/examples/v1.0/planned/delivery-create.json"
assert_file_exists "$ROOT/api/examples/v1.0/blocked/delivery-create.json"
assert_file_exists "$ROOT/api/examples/v1.0/error/delivery-create.json"
assert_file_exists "$ROOT/lib/intake-validate.sh"
assert_file_exists "$ROOT/lib/intake-validate-api.sh"
assert_file_exists "$ROOT/lib/revision-approve.sh"
assert_file_exists "$ROOT/lib/revision-approve-api.sh"
assert_file_exists "$ROOT/lib/delivery-create.sh"
assert_file_exists "$ROOT/lib/delivery-create-api.sh"
assert_file_exists "$ROOT/CHANGELOG.md"
assert_file_exists "$ROOT/docs/RELEASE_NOTES_V1.1.md"
assert_file_exists "$ROOT/docs/RELEASE_NOTES_V1.2.md"
assert_file_exists "$ROOT/docs/RELEASE_NOTES_V1.3.md"
assert_file_exists "$ROOT/docs/RELEASE_NOTES_V1.4.md"
assert_file_exists "$ROOT/docs/RELEASE_NOTES_V1.5.md"
assert_file_exists "$ROOT/docs/RELEASE_NOTES_V2.0.md"
assert_file_exists "$ROOT/docs/RELEASE_NOTES_V2.1.md"
assert_file_exists "$ROOT/docs/SCOPE_FREEZE_V1.2.md"
assert_eq "2.1.0-rc.2" "$(sed -n '1p' "$ROOT/VERSION")" \
    "v2.1.0-rc.2 application release version"
assert_eq "1.0" "$(sed -n '1p' "$ROOT/API_VERSION")" \
    "Automation API version is independent"
assert_contains "$(cat "$ROOT/.github/workflows/release.yml")" \
    'docs/RELEASE_NOTES_V2.1.md' "release workflow publishes v2.1 notes"
assert_contains "$(cat "$ROOT/.github/workflows/release.yml")" \
    'macos-15-intel' "release workflow builds Intel macOS package"
assert_contains "$(cat "$ROOT/.github/workflows/release.yml")" \
    'macos-arm64' "release workflow labels Apple Silicon package"
assert_contains "$(cat "$ROOT/docs/INSTALLATION_GUIDE.md")" \
    'xattr -dr com.apple.quarantine .' "installation guide documents unsigned macOS quarantine handling"
assert_contains "$(cat "$ROOT/docs/RELEASE_NOTES_V2.1.md")" \
    'xattr -dr com.apple.quarantine /path/to/jl-mixing-2.1.0-rc.2' "v2.1 release notes document bundled-runtime quarantine workaround"
assert_contains "$(cat "$ROOT/docs/RELEASE_NOTES_V2.1.md")" \
    'Unblock-File .\windows\install.ps1' "v2.1 release notes document Windows downloaded-script unblock"
assert_contains "$(cat "$ROOT/docs/USER_GUIDE.md")" \
    'create-delivery --clean' "user guide documents destructive clean"
assert_contains "$(cat "$ROOT/docs/USER_GUIDE.md")" \
    'create-delivery --zip --overwrite' "user guide documents edited-notes ZIP workflow"
assert_contains "$(cat "$ROOT/README.md")" \
    'existing valid v1.1+ workspaces remain compatible' "README documents v1.1+ workspace compatibility"

echo "[OK] release preparation ($TEST_COUNT assertions)"
