# JL Mixing Automation Developer Guide

## Repository architecture

```text
src/jl_mixing/   Authoritative cross-platform Python services, CLIs, and API adapters
bin/             Thin POSIX launchers and shell integration
windows/         Windows packaging/install/shell glue
macos/           macOS frozen-runtime packaging/install glue
api/             Automation API 1.0 schemas and examples
schemas/         Workspace metadata schemas (1.1.0)
templates/       Runtime JSON and Markdown templates
docs/            User, architecture, API, and release documentation
tests/           Python, integration, installation, platform, and package tests
tools/           Release/build utilities
packaging/       Runtime/build dependency metadata
```

The authoritative workflow implementation is Python. Platform-specific shell,
PowerShell, and packaging code must remain thin and must not introduce a second
workflow implementation.

## Compatibility contracts

Treat these versions independently:

- application release: v1.5.x
- Automation API: `1.0`
- workspace metadata schema: `1.1.0`

A product release does not require an API or metadata-schema bump when those
contracts remain compatible.

## Coding standards

- Keep shared workflow behavior platform-neutral in `src/jl_mixing/`.
- Preserve human CLI behavior unless a change is explicitly approved.
- Preserve Automation API 1.0 response/operation contracts.
- Reject symlinks and unsafe filesystem boundaries where JL Mixing owns data.
- Use staged/rollback-capable mutation for multi-file operations.
- Keep user-authored Markdown untouched outside explicitly managed sections.
- Keep Windows/macOS launchers and installers non-authoritative.
- Tests must use isolated temporary homes, prefixes, and workspaces.
- Do not add workspace migration for valid v1.1+ data unless explicitly approved.

Legacy Bash remains only where required for Linux/source compatibility or thin
platform glue; new workflow logic should not be added to the old Bash libraries.

## Development setup

Use a supported Python 3 environment for service/API tests. Build-time packaging
requirements are platform-specific:

```text
packaging/windows-build-requirements.txt
packaging/macos-build-requirements.txt
```

PyInstaller is used to build the private frozen runtimes shipped in Windows and
macOS release packages.

## Validation layers

1. argument/request validation
2. JSON syntax and exact schema identity
3. local Draft 2020-12 schema validation
4. cross-document identity/pointer validation
5. filesystem/path ownership validation
6. staged transaction and post-operation verification

API schemas and workspace schemas are loaded from the installed application; no
network schema dependency is required at runtime.

## Quality gates

Run the repository's Python/unit/integration suites plus platform lifecycle and
release-package checks. CI currently exercises:

- core tests and strict/release checks
- native Windows command/install/package behavior
- frozen Windows runtime
- frozen macOS runtime
- macOS self-contained installation lifecycle
- release archive/checksum/inventory verification

A release-affecting change should not merge until the applicable CI matrix is
green.

## Release process

1. Implement work on a feature/fix/release branch.
2. Open a PR to `main`; never modify `main` directly.
3. Run the complete applicable CI matrix and resolve failures on the branch.
4. Merge the green PR.
5. Prepare release-version/release-note changes on a dedicated release branch.
6. Tag the approved merge commit using the release tag expected by the release
   workflow.
7. Verify generated macOS, Windows, and Linux assets, checksums, and inventories.
8. Perform coordinated RC acceptance before publishing a stable release.

For v1.5, Windows and macOS end-user packages must remain self-contained; users
must not need a separately installed Python, Bash, or jq runtime.
