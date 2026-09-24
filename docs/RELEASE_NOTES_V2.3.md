# JL Mixing Automation 2.3

Automation 2.3 is the coordinated provider for JL Mixing Studio 2.3. It adds progress reporting and safe client/project deletion, and preserves multiline Creative Direction through the Windows launcher. Automation API remains `1.0` and readable/writable workspace metadata schemas remain `1.1.0`.

## Installation

This `v2.3.1` build was qualified with Studio `v2.3.1-rc.2` on Windows 11 Pro and macOS Intel 12.7.6. Download its archive for your platform and verify its accompanying SHA-256 checksum before installing.

- Windows: extract `jl-mixing-2.3.1-windows.zip`, then run `.\windows\install.ps1` in PowerShell. If the script is blocked, run `Unblock-File .\windows\install.ps1` first. The package contains a private Python runtime.
- Intel Mac: choose the `macos-x86_64` archive. Apple Silicon Mac: choose `macos-arm64`. The packages are unsigned and not notarized. After checksum verification, remove quarantine recursively from the extracted folder with `xattr -dr com.apple.quarantine /path/to/jl-mixing-<version>`, then run `./macos/install.sh` from that folder. The bundled Python runtime requires this step.
- Linux/source compatibility package: extract and run `./install.sh`. Bash, Python 3.10+ with `venv`, and jq are required.

Open a new shell after installation if needed and verify with `jl-mixing --version`. `ffprobe`/`ffmpeg` remain optional for enhanced audio intake QC.

## Changes

- Audio Prep Reset advertises `audio.prep.reset.progress` and can stream real `JL_PROGRESS` count events through `--progress=stderr-json`; existing callers remain compatible. Reset completion is reported only after successful execution and lineage recording.
- Project deletion provides an authoritative pre-delete summary and requires exact typed project name confirmation in Studio. External Listening copies remain untouched. There is no built-in recovery.
- Client deletion is limited to clients with no projects, summarizes remaining client content, and requires exact typed client name confirmation in Studio. It cannot cascade into project deletion.
- This release fixes client deletion on valid relocated/NAS workspaces whose legacy `studio.json` ownership root no longer matches the current path (Automation #206). The existing document, inventory, and exact-name safeguards remain.
- Multiline UTF-8 Creative Direction text crosses the Windows launcher safely and preserves LF/CRLF line breaks. Existing empty and single-line values keep their behavior.

## Compatibility and verification

Existing valid v1.1+ workspaces remain compatible and no metadata schema migration is introduced. Consumers should use API discovery and advertised capabilities. The implementation PRs passed CI; coordinated candidate packages passed the approved Windows and macOS Intel acceptance checks. Apple Silicon was not run because a test machine was unavailable. The [2.3 release acceptance record](https://github.com/jl-aspect-works/jl-mixing-studio/blob/main/docs/RELEASE_ACCEPTANCE_V2.3.md) identifies the tested candidate builds and results.
