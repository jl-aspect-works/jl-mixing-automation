# JL Mixing Automation 2.0

JL Mixing Automation 2.0 supplies the authoritative workflow and machine-readable API support used by the JL Mixing Studio 2.0 Daily Workflow release.

## Installation

Download the release archive for your platform from the Assets section below and verify its accompanying SHA-256 checksum before installing.

### macOS

Choose the archive that matches your Mac:

- `macos-arm64` for Apple Silicon Macs.
- `macos-x86_64` for Intel Macs.

Extract the archive. JL Mixing Automation 2.0 is currently unsigned and not notarized. macOS may therefore block the bundled Python runtime with a message such as **“Python cannot be opened because Apple cannot check it for malicious software.”**

After verifying the checksum, remove the macOS quarantine attribute recursively from the extracted release directory:

```bash
xattr -dr com.apple.quarantine /path/to/jl-mixing-2.0.0
```

For example, if the extracted folder is in Downloads:

```bash
xattr -dr com.apple.quarantine "$HOME/Downloads/jl-mixing-2.0.0"
```

Then run the installer:

```bash
cd "$HOME/Downloads/jl-mixing-2.0.0"
./macos/install.sh
```

The recursive quarantine removal is important because the release contains a bundled Python framework/runtime; clearing quarantine only from `install.sh` is not sufficient.

The macOS package includes its private Python runtime and installs to `~/.local` by default. Open a new Terminal session after installation if needed, then verify:

```bash
jl-mixing --version
```

### Windows

Download and extract `jl-mixing-2.0.0-windows.zip`, then run the included PowerShell installer from the extracted release directory:

```powershell
.\windows\install.ps1
```

If Windows marks the downloaded script as blocked, clear the downloaded-file mark and run it again:

```powershell
Unblock-File .\windows\install.ps1
.\windows\install.ps1
```

The Windows package includes its private Python runtime. End users do not need to install Python, Bash, or jq separately. The default installation is beneath `%LOCALAPPDATA%\Programs\JL Mixing\`.

Open a new PowerShell session after installation so the managed PATH and shell integration are active, then verify:

```powershell
jl-mixing --version
```

### Linux

Download and extract the Linux release archive, then run the compatibility installer from the extracted directory:

```bash
./install.sh
```

Linux/source installs require Bash, Python 3.10+ with `venv`, and jq. After installation, verify:

```bash
jl-mixing --version
```

`ffprobe`/`ffmpeg` are optional external tools used for enhanced audio intake QC. When unavailable, affected checks are reported as skipped rather than silently assumed to have passed.

## Highlights

- Structured incremental intake validation for Studio, including cached file-level findings and technical metadata.
- Structured Audio Prep validation and exact-content provenance so Studio can show authoritative preparation state and source-file relationships without guessing.
- Revision-description mutation through Automation-owned metadata handling.
- Managed Delivery status and reconciliation, including missing, mismatched, unsafe, and untracked artifact detection.
- Generated Delivery package current/stale verification that incorporates the current Delivery Notes content.
- Safe generated-package deletion and authoritative package rebuild through the existing delivery creation workflow.
- Explicit failed-mutation safety coverage confirming existing authoritative Delivery state is preserved when package deletion fails.
- Native Windows runtime/install support from the 1.5 release line remains included.

## Compatibility

Automation 2.0 keeps the existing Automation API identity at **1.0** and keeps the supported workspace metadata schema identity at **1.1.0**. Application release versions remain independent from API and metadata schema versions.

Existing valid v1.1-schema workspaces remain compatible. No workspace migration is introduced by the 2.0 application release.

Studio compatibility continues to be determined from Automation API version and advertised capabilities, not by requiring Studio and Automation product version numbers to match.

## Delivery safety

Studio may inspect managed Delivery state and invoke explicitly supported package operations, but manifest-managed deliverables remain Automation-owned. Automation does not expose unrestricted filesystem mutation of `05_Final_Delivery`.

Generated package deletion is restricted to JL Mixing package filenames for the current project. Rebuilds continue to use the existing authoritative `delivery create --overwrite --zip` semantics, preserving manifest/hash consistency and current Delivery Notes.

## Explicitly deferred beyond 2.0

- Audio Prep repair, normalization, Fix/Convert, or format-conversion mutations.
- Unrestricted managed-deliverable rename/delete operations.
- Generic filesystem management outside the defined Automation workflows.
- Real-time multi-user conflict resolution.

## Validation

The stable release is promoted from the coordinated 2.0 release-candidate cycle after packaged JL Mixing Studio validation on macOS and Windows. Automation API remains `1.0`; workspace metadata schema remains `1.1.0`.
