# Changelog

## 2.2.0-rc.1

- Added optional revision-relative `source_path` provenance to delivery-manifest file records so downstream consumers can identify the authoritative revision source used for each packaged file.
- Kept existing delivery manifests valid and preserved Automation API `1.0` and workspace metadata schema `1.1.0`.
- Added one platform-neutral policy that ignores `.DS_Store`, AppleDouble `._*`, `Thumbs.db`, and `desktop.ini` across Delivery, Intake, managed imports, Audio Prep, source imports, provenance recovery, and generated delivery ZIP reconciliation.
- Preserved legitimate dotfiles as project content; ignored operating-system metadata is not deleted merely because it is discovered.
- Added cross-platform regression coverage for delivery provenance and filesystem-noise handling required by Studio 2.2 Listening workflows.

## 2.1.0

- Added Automation-owned Studio, client, and project metadata update capabilities used by Studio v2.1.
- Added managed Client Files import planning/execution with selected-file support and safe Audio Prep reset workflows.
- Added reversible revision Close/Reopen and approval Unapprove lifecycle operations without destructive revision deletion.
- Added capability discovery for the new v2.1 workflow operations while preserving Automation API `1.0` and metadata schema `1.1.0`.
- Reduced repeated Working Audio hashing during managed provenance recovery by building one lazy hash index per plan.
- Preserved path containment, provenance ambiguity checks, stale-plan validation, transactional mutation behavior, and existing valid v1.1+ workspace compatibility.

## 2.0.0

- Added incremental cached intake validation with structured per-file findings and technical metadata for Studio.
- Added structured Audio Prep validation and exact-content provenance for unchanged Working Audio files.
- Added Automation-owned revision-description mutation through API 1.0.
- Added managed Delivery status/reconciliation, generated-package current/stale detection, safe generated-package deletion, and authoritative rebuild support.
- Added failure-safety regression coverage proving failed package deletion preserves existing authoritative Delivery state.
- Preserved Automation API `1.0`, workspace metadata schema `1.1.0`, existing valid v1.1 workspaces, and the cross-platform runtime/install architecture established in the 1.5 line.
- Added stable 2.0 installation guidance, including the recursive macOS quarantine workaround required by the unsigned bundled Python runtime and Windows downloaded-script unblock guidance.

## 1.5.1

- Split the self-contained macOS release into architecture-specific Intel
  (`macos-x86_64`) and Apple Silicon (`macos-arm64`) packages.
- Added a release-time architecture assertion for the bundled macOS PyInstaller
  runtime so an archive cannot be published under the wrong CPU label.
- Replaced the moving `macos-latest` release runner with explicit Intel and Apple
  Silicon runner labels.
- Kept Automation API 1.0, metadata schema 1.1.0, human CLI behavior, Windows
  packaging, Linux packaging, and workspace semantics unchanged.

## 1.5.0

- Replaced the authoritative Bash workflow implementation with one shared Python
  runtime while preserving the v1.4 human CLI and Automation API 1.0 contracts.
- Added first-class Windows support for all public commands, PowerShell parent-
  shell directory changes, workspace/path safety, installation, rollback, and
  release packaging.
- Added self-contained PyInstaller runtimes for Windows and macOS so packaged
  end-user installs do not require a separately installed Python interpreter.
- Added a transactional Windows installer/uninstaller with managed PowerShell
  profile integration and workspace-preserving cleanup.
- Added a transactional self-contained macOS installer/uninstaller that does not
  require external Python or jq and preserves existing bash/zsh integration.
- Added native Windows CI plus macOS/Ubuntu compatibility regressions covering
  the shared Python runtime, API adapters, human CLIs, install/rollback behavior,
  package extraction, and release artifacts.
- Added Windows ZIP releases with SHA-256 checksums and inventory files while
  retaining macOS/Linux tarball release artifacts.
- Added `new-client --root PATH` with explicit root precedence across the flag,
  `JL_MIXING_ROOT`, current studio context, and the default `~/Music/Mixes` root.
- Kept Automation API version 1.0 and workspace metadata schema version 1.1.0;
  no workspace migration or workflow redesign is introduced.

## 1.4.0

- Added the structured Automation API 1.0 workflow operations used by JL Mixing
  Studio v1.1: client/project creation, intake validation, revision creation and
  approval, and delivery creation.
- Added additive capability discovery for the completed workflow API surface.
- Added provider-authored effective project artist and revision description
  results plus authoritative intake report content for Studio reconciliation.
- Expanded `delivery.create` results with selected/excluded files and clean-mode
  deletion inventory required for safe Studio preview/confirm/commit handling.
- Added SemVer prerelease/build-version support for application release identity,
  API discovery, and persisted `created_with` provenance so release candidates
  can be tested against real workspaces without changing metadata schema 1.1.0.
- Preserved the existing human-facing CLI workflows and v1.1 workspace schemas.

## 1.3.0

- Name delivery ZIPs with the project ID, zero-padded delivered revision, and
  local creation timestamp: `<project-id>-rev-<NN>-<YYYYMMDDHHMMSS>.zip`.
- Preserve earlier generated archives without nesting them inside later ZIPs.

## 1.2.0

- Added positional project-name support to `new-mix` while preserving `--project`.
- Added client-name fallback when the client artist default is empty.
- Added transactional creation of unapproved Revision 1 during `new-mix`.
- Documented and regression-tested the two-step ZIP workflow that preserves
  completed `Delivery_Notes.md`.
- Decoupled application release provenance from metadata schema versioning:
  v1.2 writes `created_with: jl-mixing 1.2.0` while retaining the v1.1.0 schema.
- Preserved v1.1 workspace schema identities, document structures, and existing
  v1.1 compatibility.

## 1.1.0

- Flattened project storage and removed completion lifecycle directories.
- Removed JL-managed DAW resources and metadata.
- Added strict v1.1 schemas and immutable client/delivery snapshots.
- Added three-pointer revision state and older-revision approval support.
- Preserved v1.0.4 intake validation behavior with improved report layout.
- Added extension-neutral, SHA-256-verified final delivery with best-effort
  classification and destructive clean replacement.
- Added automatic bash/zsh integration, transactional install/upgrade/uninstall,
  and expanded release verification.
