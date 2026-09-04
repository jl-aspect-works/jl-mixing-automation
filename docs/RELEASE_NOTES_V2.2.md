# JL Mixing Automation 2.2

JL Mixing Automation 2.2 is the coordinated provider release for JL Mixing Studio 2.2. It adds delivery-source provenance and consistent operating-system metadata filtering needed by Studio's Delivered Listening workflow without changing Automation API `1.0` or workspace metadata schema `1.1.0`.

Automation 2.2.0 was qualified through coordinated packaged acceptance with JL Mixing Studio 2.2 on Windows and macOS Intel. Apple Silicon manual acceptance was deferred because suitable hardware was unavailable; the published Apple Silicon package and required automated architecture checks passed.

## Installation

Download the release archive for your platform from the Assets section and verify its accompanying SHA-256 checksum before installing. Replace `<version>` below with the version shown on the release (`2.2.0` for this stable release).

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

## Delivery source provenance

- Delivery-manifest file records can include an optional revision-relative `source_path` identifying the authoritative revision source used for that packaged file.
- Provenance distinguishes revision-root primary files from files beneath `Variants/`.
- Existing path, classification, hash, and replacement behavior remains unchanged.
- Older delivery manifests without `source_path` remain valid and are supported by Studio's conservative legacy fallback.

Studio `2.2.0` is coordinated with Automation `2.2.0`. Stable qualification used the accepted `2.2.0-rc.1` pair to verify that the Delivered Listening primary copy follows the exact source used by Automation's delivery package.

## Operating-system metadata handling

Automation uses one platform-neutral ignore policy for known filesystem noise:

- `.DS_Store`
- AppleDouble `._*`
- `Thumbs.db`
- `desktop.ini`

The policy applies across Delivery source enumeration and generated ZIP reconciliation, Intake inventory/reporting, managed Client Files imports, Audio Prep matching/status, provenance recovery, and project/revision source imports. It applies regardless of the current host OS so local, NAS/shared, and synchronized workspaces behave consistently.

Ignored metadata is not packaged or treated as project content. It is not deleted merely because Automation discovers it. Other dotfiles remain normal project content.

## Compatibility

- Automation API: `1.0`
- readable workspace metadata schema: `1.1.0`
- writable workspace metadata schema: `1.1.0`
- existing valid v1.1+ workspaces and legacy delivery manifests remain compatible
- no workspace migration is introduced by 2.2

Application release, API version, and metadata schema remain independent. Consumers must use API discovery and advertised capabilities rather than requiring matching product versions.

## Release qualification

The provenance and filesystem-noise changes passed cross-platform branch/runtime coverage, packaged Automation installation/runtime checks, and coordinated Studio 2.2 acceptance. No release-blocking finding remained after the accepted RC1 cycle.
