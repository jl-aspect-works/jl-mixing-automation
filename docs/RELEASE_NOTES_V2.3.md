# JL Mixing Automation 2.3

Automation `v2.3.3` is the stable security and dependency-maintenance release promoted from the qualified `v2.3.3-rc.1` candidate. It pairs with Studio `v2.3.3`. No product-behavior, Automation API, or workspace metadata schema change is introduced by the stable promotion; Automation API remains `1.0` and readable/writable workspace metadata schemas remain `1.1.0`.

## Installation

Download the `v2.3.3` archive for your platform and verify its accompanying SHA-256 checksum before installing. This stable release pairs with Studio `v2.3.3`. The release workflow also generates GitHub artifact provenance attestations for the published files.

- Windows: extract `jl-mixing-2.3.3-windows.zip`, then run `.\windows\install.ps1` in PowerShell. If the script is blocked, run `Unblock-File .\windows\install.ps1` first. The package contains a private Python runtime.
- Intel Mac: choose the `macos-x86_64` archive. Apple Silicon Mac: choose `macos-arm64`. The packages are unsigned and not notarized. After checksum verification, remove quarantine recursively from the extracted folder with `xattr -dr com.apple.quarantine /path/to/jl-mixing-<version>`, then run `./macos/install.sh` from that folder. The bundled Python runtime requires this step.
- Linux/source compatibility package: extract and run `./install.sh`. Bash, Python 3.10+ with `venv`, and jq are required.

Open a new shell after installation if needed and verify with `jl-mixing --version`. `ffprobe`/`ffmpeg` remain optional for enhanced audio intake QC.

## Changes

- **Security and dependency maintenance (v2.3.3):** Hardens GitHub Actions permissions and immutable action pins, configures Dependabot version updates, applies routine Actions/PyInstaller updates, adds a repository security policy, regression-tests the CI documentation-only classifier, and adds GitHub artifact provenance attestations to the release workflow. No intentional runtime behavior, API, or workspace-schema change is included.
- **New in 2.3.2:** `client.files.delete.plan` and `client.files.delete.execute` provide an authoritative deletion plan for a selected Client Files entry. Deleting an imported Original Delivery source also removes its managed lineage while retaining Working Audio copies; protected roots, symlinks, and dependent content are rejected. Deletion is permanent and requires confirmation in Studio.
- Audio Prep Reset advertises `audio.prep.reset.progress` and can stream real `JL_PROGRESS` count events through `--progress=stderr-json`; existing callers remain compatible. Reset completion is reported only after successful execution and lineage recording.
- Project deletion provides an authoritative pre-delete summary and requires exact typed project name confirmation in Studio. External Listening copies remain untouched. There is no built-in recovery.
- Client deletion is limited to clients with no projects, summarizes remaining client content, and requires exact typed client name confirmation in Studio. It cannot cascade into project deletion.
- This release fixes client deletion on valid relocated/NAS workspaces whose legacy `studio.json` ownership root no longer matches the current path (Automation #206). The existing document, inventory, and exact-name safeguards remain.
- Multiline UTF-8 Creative Direction text crosses the Windows launcher safely and preserves LF/CRLF line breaks. Existing empty and single-line values keep their behavior.

## Compatibility and verification

Existing valid v1.1+ workspaces remain compatible and no metadata schema migration is introduced. Consumers should use API discovery and advertised capabilities. Automation `v2.3.3-rc.1` with Studio `v2.3.3-rc.2` passed the final security-hardening qualification, including end-to-end verification of release artifact attestations, on Windows x64 and macOS Intel; Apple Silicon installed acceptance was not run because hardware was unavailable. Stable `v2.3.3` contains no intentional runtime change from that qualified Automation candidate.
