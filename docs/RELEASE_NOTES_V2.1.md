# JL Mixing Automation 2.1

JL Mixing Automation 2.1 supplies the authoritative workflow capabilities used by the JL Mixing Studio 2.1 release. It extends the existing Automation API 1.0 surface without changing workspace metadata schema 1.1.0.

## Installation

Download the release archive for your platform from the Assets section and verify its accompanying SHA-256 checksum before installing. Replace `<version>` below with the version shown on the release, for example `2.1.0-rc.3`.

### macOS

Choose the archive that matches your Mac:

- `macos-arm64` for Apple Silicon Macs.
- `macos-x86_64` for Intel Macs.

The packages remain unsigned and not notarized. After verifying the checksum, remove quarantine recursively from the extracted release directory before running the installer:

```bash
xattr -dr com.apple.quarantine /path/to/jl-mixing-<version>
cd /path/to/jl-mixing-<version>
./macos/install.sh
```

The recursive quarantine removal is required because the archive contains a bundled Python runtime. The default install prefix is `~/.local`. Open a new Terminal session after installation if needed, then verify:

```bash
jl-mixing --version
```

### Windows

Download and extract `jl-mixing-<version>-windows.zip`, then run:

```powershell
.\windows\install.ps1
```

If Windows marks the downloaded installer script as blocked:

```powershell
Unblock-File .\windows\install.ps1
.\windows\install.ps1
```

The Windows package includes its private Python runtime. The default installation remains beneath `%LOCALAPPDATA%\Programs\JL Mixing\`. Open a new PowerShell session after installation, then verify with `jl-mixing --version`.

### Linux

The Linux/source compatibility package remains available. Extract it and run:

```bash
./install.sh
```

Linux/source installs require Bash, Python 3.10+ with `venv`, and jq.

`ffprobe` and `ffmpeg` remain optional external tools used for enhanced audio intake QC. Unavailable checks are reported as skipped.

## Highlights

- Automation-owned Studio, client, and project metadata updates for Studio 2.1 editing workflows.
- Managed Client Files import with plan/execute safety, per-file selection support, stale-plan validation, and NAS-safe content-only copy behavior on macOS shared workspaces.
- Managed Audio Prep reset from the current Client Files source while preserving path-safety and transactional behavior.
- Reversible revision Close/Reopen lifecycle so abandoned or mistaken revisions do not permanently hold a project in an attention state.
- Reversible Unapprove support for approved revisions without deleting revision files or history.
- Additive API capability discovery for the new Studio 2.1 operations.
- Reduced repeated Working Audio hashing during managed provenance recovery by building one lazy hash index per plan.

## Compatibility

Automation 2.1 keeps:

- Automation API: `1.0`
- readable workspace metadata schema: `1.1.0`
- writable workspace metadata schema: `1.1.0`
- compatibility with existing valid v1.1+ workspaces

No workspace migration is introduced by 2.1. Studio compatibility remains determined from API version and advertised capabilities rather than requiring matching Studio and Automation application version numbers.

## Workflow safety

The new v2.1 mutations remain Automation-owned and preserve the existing safety model:

- path containment and symlink protections
- plan/execute validation for managed import/reset operations
- stale-plan rejection before mutation
- provenance ambiguity handling
- transactional mutation behavior
- authoritative metadata conflict checks

Closing a revision is non-destructive; it does not delete the revision directory or its history. Unapprove changes approval metadata only and does not delete revision files or prior Delivery artifacts.

## Explicitly deferred

- Audio repair, normalization, or general Fix/Convert mutations.
- Generic filesystem management outside defined Automation workflows.
- Unrestricted managed-deliverable rename/delete operations.
- Real-time multi-user conflict resolution.

## Release-candidate validation

Prerelease versions of 2.1 are intended for coordinated packaged validation with the corresponding JL Mixing Studio 2.1 candidate on Windows and macOS before promotion to the stable 2.1 release.
