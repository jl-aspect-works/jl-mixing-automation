#!/usr/bin/env bash
# Release test orchestrator.
#
# Basic mode runs all available checks and visibly skips dependency-bound work.
# Strict mode requires the complete runtime stack and adds installation/release
# lifecycle verification.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Verifying v$(cat VERSION) repository artifacts..."

required='README.md
VERSION
API_VERSION
Makefile
install.sh
uninstall.sh
docs/DESIGN_SPECIFICATION_V1.md
docs/USER_GUIDE.md
docs/SCRIPT_REFERENCE.md
docs/INSTALLATION_GUIDE.md
docs/AUTOMATION_API.md
docs/AUTOMATION_API_IMPLEMENTATION.md
docs/DEVELOPER_GUIDE.md
docs/ARCHITECTURE_DECISIONS.md
docs/SCOPE_FREEZE_V1.md
docs/SCOPE_FREEZE_V1.2.md
docs/PROJECT_MAINTENANCE.md
docs/RELEASE_NOTES_V1.1.md
docs/RELEASE_NOTES_V1.2.md
docs/RELEASE_NOTES_V1.3.md
CHANGELOG.md
api/schemas/v1.0/system-info.schema.json
api/schemas/v1.0/response-envelope.schema.json
api/schemas/v1.0/error.schema.json
api/schemas/v1.0/warning.schema.json
api/schemas/v1.0/operations/client-create.schema.json
api/examples/v1.0/success/client-create.json
api/examples/v1.0/planned/client-create.json
api/examples/v1.0/error/client-create.json
api/examples/v1.0/success/system-info.json
schemas/studio.schema.json
schemas/client.schema.json
schemas/client-profile-snapshot.schema.json
schemas/project-manifest.schema.json
schemas/delivery-manifest.schema.json
templates/README.md
templates/studio/studio.json.template
templates/client/client.json.template
templates/Intake_Report.md
templates/Project_Notes.md
templates/Preparation_Report.md
templates/Revision_Notes.md
templates/Delivery_Notes.md
templates/Recall_Sheet.md
packaging/requirements.txt
packaging/RELEASE_README.md
lib/common.sh
lib/platform.sh
lib/filesystem.sh
lib/json.sh
lib/metadata.sh
lib/config.sh
lib/context.sh
lib/naming.sh
lib/templates.sh
lib/validation.sh
lib/revision.sh
lib/transaction.sh
lib/project-state.sh
bin/jl-mixing
bin/new-studio
bin/new-client
bin/new-mix
bin/validate-intake
bin/new-revision
bin/approve-mix
bin/create-delivery
bin/jl-mixing-shell-integration
tools/build-intake-report.py
tools/project-state.py
tools/import-project-source.py
tools/import-revision-source.py
tools/build-delivery.py
tools/manage-shell-config.py
tools/build-release
tools/verify-release-archive'

echo "$required" | while IFS= read -r path; do
    [ -n "$path" ] || continue
    [ -f "$path" ] || { echo "Missing required artifact: $path" >&2; exit 1; }
done
echo "[OK] Required artifacts"

python3 - <<'PY'
import json
from pathlib import Path
for directory in ('api/schemas', 'api/examples', 'schemas', 'examples', 'tests/fixtures'):
    for path in Path(directory).rglob('*.json'):
        json.loads(path.read_text())
print('[OK] JSON syntax')
PY

# Syntax-check only files whose extension or shebang identifies shell code.
for path in install.sh uninstall.sh bin/* lib/*.sh tests/*.sh tests/unit/*.sh \
    tests/integration/*.sh tests/installation/*.sh tools/*; do
    [ -f "$path" ] || continue
    first_line="$(sed -n '1p' "$path")"
    case "$path:$first_line" in
        *.sh:*|*:'#!'*'/sh'|*:'#!'*'/bash'|*:'#!'*'env sh'|*:'#!'*'env bash')
            bash -n "$path"
            ;;
    esac
done
echo "[OK] Shell syntax"

for test_file in tests/unit/test-*.sh; do
    echo
    echo "Running $test_file"
    bash "$test_file"
done

validator_python="${JL_MIXING_PYTHON:-}"
if [ -z "$validator_python" ] && [ -x "$ROOT/.venv/bin/python" ]; then
    validator_python="$ROOT/.venv/bin/python"
fi
if [ -z "$validator_python" ]; then
    validator_python="$(command -v python3 || true)"
fi

runtime_available=1
command -v jq >/dev/null 2>&1 || runtime_available=0
[ -n "$validator_python" ] || runtime_available=0
if [ "$runtime_available" -eq 1 ]; then
    "$validator_python" -c 'import jsonschema' >/dev/null 2>&1 || runtime_available=0
fi

if [ "$runtime_available" -eq 1 ]; then
    export JL_MIXING_PYTHON="$validator_python"
    echo
    echo "Running command integration tests..."
    for test_file in tests/integration/test-*.sh; do
        echo
        echo "Running $test_file"
        bash "$test_file"
    done
    echo
    "$validator_python" tools/validate-json.py --strict

    # Installation and archive verification are release-level checks. Strict
    # mode requires them; basic mode omits them to remain quick and non-networked.
    if [ "${JL_TEST_STRICT:-0}" = "1" ]; then
        echo
        echo "Running installation and release tests..."
        for test_file in tests/installation/test-*.sh; do
            echo
            echo "Running $test_file"
            bash "$test_file"
        done
    fi
else
    if [ "${JL_TEST_STRICT:-0}" = "1" ]; then
        echo "[FAIL] Strict tests require jq, Python 3, and jsonschema." >&2
        exit 1
    fi
    echo
    echo "[SKIP] Integration and semantic schema tests require jq and jsonschema."
    python3 tools/validate-json.py
fi

echo
if [ "${JL_TEST_STRICT:-0}" = "1" ]; then
    echo "[OK] v1.1 strict verification passed"
else
    echo "[OK] v1.1 verification passed"
fi
