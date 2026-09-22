#!/usr/bin/env bash
# Reusable fixtures for command-level integration tests.
#
# Every fixture is created under a temporary studio root; tests never touch the
# user's real JL Mixing workspace.
set -eu

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=tests/test-helper.sh
. "$ROOT/tests/test-helper.sh"

export JL_MIXING_HOME="$ROOT"

# Create a deliberately incompatible v1.0-style workspace for migration
# diagnostic tests. Active v1.1 workflow tests use fixture_v11_project below.
fixture_studio() {
    local studio_root
    studio_root="$1"
    mkdir -p "$studio_root/Studio" "$studio_root/Clients"
    cat > "$studio_root/Studio/studio.json" <<'EOF_LEGACY_STUDIO'
{"metadata":{"schema":"mixing-studio","schema_version":"1.0.4"}}
EOF_LEGACY_STUDIO
}

# Generate a small valid 48 kHz, 24-bit stereo WAV fixture.
fixture_wav() {
    local path
    path="$1"
    python3 - "$path" <<'PY_WAV'
import sys
import wave
from pathlib import Path

# Generate a tiny silent file; audio content is irrelevant to workflow tests.
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(path), "wb") as output:
    output.setnchannels(2)
    output.setsampwidth(3)
    output.setframerate(48000)
    # A 24-bit stereo frame contains two signed three-byte samples.
    silent_frame = (0).to_bytes(3, "little", signed=True) * 2
    output.writeframes(silent_frame * 480)
PY_WAV
}

# Create a complete canonical v1.1 project in Setup state without invoking the
# slower project-creation command. Revision-workflow tests use this fixture to
# focus on the commands under test while still validating every governing JSON
# document and standard directory boundary.
fixture_v11_project() {
    local studio_root client_root project_root manifest
    studio_root="$1"
    client_root="$studio_root/Clients/Acme Records"
    project_root="$client_root/Projects/Blue Sky"

    mkdir -p \
        "$studio_root/Studio" \
        "$client_root/Projects" \
        "$project_root/00_Admin" \
        "$project_root/01_Client_Files/Original_Delivery" \
        "$project_root/01_Client_Files/References" \
        "$project_root/01_Client_Files/Documentation" \
        "$project_root/02_Audio_Preparation/Working_Audio" \
        "$project_root/02_Audio_Preparation/Rejected_Files" \
        "$project_root/03_DAW_Project" \
        "$project_root/04_Revisions" \
        "$project_root/05_Final_Delivery/Stems" \
        "$project_root/06_Recall/External_Files" \
        "$project_root/06_Recall/Screenshots"

    jq --arg root "$studio_root" '.root_path=$root' \
        "$ROOT/examples/studio.json" > "$studio_root/Studio/studio.json"
    cp "$ROOT/examples/client.json" "$client_root/client.json"
    cp "$ROOT/examples/client-profile-snapshot.json" \
        "$project_root/00_Admin/client-profile-snapshot.json"
    manifest="$project_root/00_Admin/project-manifest.json"
    jq '.state={current_revision:0,approved_revision:null,delivered_revision:null} |
        .revisions=[]' "$ROOT/examples/project-manifest.json" > "$manifest"

    cp "$ROOT/templates/Intake_Report.md" "$project_root/00_Admin/Intake_Report.md"
    cp "$ROOT/templates/Project_Notes.md" "$project_root/00_Admin/Project_Notes.md"
    cp "$ROOT/templates/Preparation_Report.md" \
        "$project_root/02_Audio_Preparation/Preparation_Report.md"
    cp "$ROOT/templates/Delivery_Notes.md" \
        "$project_root/05_Final_Delivery/Delivery_Notes.md"
    cp "$ROOT/templates/Recall_Sheet.md" "$project_root/06_Recall/Recall_Sheet.md"

    printf '%s\n' "$project_root"
}

# Create a canonical v1.1 project with one approved flattened revision. Delivery
# tests use this fixture to focus on package behavior without invoking the slower
# revision and approval commands before every test file.
fixture_v11_approved_project() {
    local studio_root project_root manifest revision_root
    studio_root="$1"
    project_root="$(fixture_v11_project "$studio_root")"
    manifest="$project_root/00_Admin/project-manifest.json"
    revision_root="$project_root/04_Revisions/Revision_01"
    mkdir -p "$revision_root"
    printf '# Revision 1 Notes\n' > "$revision_root/Revision_Notes.md"
    jq '.state={current_revision:1,approved_revision:1,delivered_revision:null} |
        .revisions=[{number:1,revision_id:"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            created_at:"2029-12-31T12:00:00Z",description:"Final balance",
            approval:{approved_at:"2030-01-01T12:00:00Z",approved_by:"Client"}}]' \
        "$manifest" > "$manifest.tmp"
    mv "$manifest.tmp" "$manifest"
    printf '%s\n' "$project_root"
}
