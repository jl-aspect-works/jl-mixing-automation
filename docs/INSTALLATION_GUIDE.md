# JL Mixing Automation v1.5 Installation Guide

JL Mixing Automation v1.5 provides platform-specific packages. Windows and
macOS packages include the private Python runtime used by Automation; Linux and
source/developer installs retain the compatibility installer.

## Windows

### Requirements

- Windows x64
- PowerShell

No separate Python, Bash, or jq installation is required.

### Install

Extract `jl-mixing-<version>-windows.zip`, open PowerShell in the extracted
folder, and run:

```powershell
.\windows\install.ps1
```

The default prefix is:

```text
%LOCALAPPDATA%\Programs\JL Mixing
```

The application is installed beneath `share\jl-mixing`, and public command
launchers are installed beneath `bin`. The installer manages a PowerShell
profile block that adds the command directory to PATH and loads the optional
`--cd` shell integration. Open a new PowerShell session after installation.

To skip profile changes:

```powershell
.\windows\install.ps1 -NoShellIntegration
```

To use another prefix:

```powershell
.\windows\install.ps1 -Prefix "C:\Tools\JL Mixing"
```

### Uninstall

Run the matching packaged uninstaller with the same prefix when applicable:

```powershell
.\windows\uninstall.ps1
```

or:

```powershell
.\windows\uninstall.ps1 -Prefix "C:\Tools\JL Mixing"
```

The uninstaller removes only JL Mixing-managed application files, launchers, and
PowerShell profile integration. Studio workspaces are not modified.

## macOS

### Requirements

The release archive contains its private runtime. A separate Python or jq install
is not required for the packaged macOS path.

Download the package matching the Mac architecture:

- Intel: `jl-mixing-<version>-macos-x86_64.tar.gz`
- Apple Silicon: `jl-mixing-<version>-macos-arm64.tar.gz`

Run `uname -m` when needed: `x86_64` means Intel and `arm64` means Apple Silicon.

### Unsigned release note

The current macOS release packages are not Developer ID signed or notarized.
Downloaded archives can therefore carry the macOS quarantine attribute, causing
Gatekeeper to block the bundled runtime or `Python.framework` even after the
archive checksum and CPU architecture are correct.

Before removing quarantine, verify the downloaded archive against its matching
`.sha256` file. Then extract the archive, change into the extracted
`jl-mixing-<version>` directory, and remove quarantine from that verified copy:

```bash
xattr -dr com.apple.quarantine .
```

Do not run the quarantine-removal command on an archive or directory whose
origin and checksum you have not verified. Signing and notarization are tracked
separately from the v1.5.1 architecture packaging fix.

### Install

After choosing the matching architecture package and completing the unsigned
release step above when required, run:

```bash
./macos/install.sh
```

The default prefix is `~/.local`:

```text
Application: ~/.local/share/jl-mixing/
Commands:    ~/.local/bin/
```

The installer manages exactly one block in `.zshrc` or `.bashrc` for PATH and
optional `--cd` integration. Existing content outside that managed block is
preserved. Open a new Terminal tab after installation.

To skip shell integration:

```bash
./macos/install.sh --no-shell-integration
```

To use another prefix:

```bash
./macos/install.sh --prefix "$HOME/Applications/jl-local"
```

### Uninstall

From an extracted matching package, run:

```bash
./macos/uninstall.sh
```

Use `--prefix PATH` when the application was installed under a custom prefix.
The uninstaller removes managed application files, launchers, and the managed
shell block while preserving workspaces and project content.

## Linux and source/developer installation

The compatibility installer remains:

```bash
./install.sh
```

Requirements for this path are:

- Bash 3.2 or newer
- Python 3.10 or newer with `venv`
- jq

The default prefix is `~/.local`. `--prefix` and `--no-shell-integration` remain
available. This installer may create a private virtual environment and therefore
is distinct from the frozen runtime included in Windows/macOS release packages.
The top-level `./install.sh` also remains a macOS compatibility/fallback path
when these host dependencies are present.

## Optional intake-QC tools

`ffprobe` and `ffmpeg` enable enhanced audio intake checks such as metadata
inspection and full-file decode verification. When an external check is not
available, `validate-intake` reports it as skipped rather than treating it as a
pass.

## Verify an installation

After opening a new shell, run:

```text
jl-mixing system-info --json
```

The response reports:

- Automation API version (`1.0`)
- installed application version
- readable and writable metadata schemas (`1.1.0`)
- implemented API capabilities
- installed API schema location

You can also verify the human command surface with:

```text
new-client --help
new-mix --help
validate-intake --help
```

## Upgrade/reinstall behavior

Reinstall using the newer package for the same platform and prefix. Installers
stage and validate managed application state before replacing the prior install.
User workspaces are outside the application prefix and are not migrated or
removed during install, reinstall, or uninstall.

## Workspace compatibility

v1.5 continues to read and write metadata schema `1.1.0`. Existing valid v1.1+
workspaces remain usable. v1.0 workspace contents are not migrated.
