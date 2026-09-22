# JL Mixing Automation v1.4.0 Release Notes

JL Mixing Automation v1.4 is the first release intended as the coordinated
Automation provider for JL Mixing Studio v1.1. It completes the structured
Automation API 1.0 workflow surface used by Studio while preserving the
existing human-facing CLI workflows and v1.1 workspace metadata schemas.

## Highlights

- Automation API 1.0 discovery remains available through
  `jl-mixing system-info --json`.
- Structured workflow operations are available for:
  - `client.create`
  - `project.create`
  - `revision.create`
  - `intake.validate`
  - `revision.approve`
  - `delivery.create`
- Workflow operations use the common API 1.0 response envelope, stable
  machine-readable status/error behavior, and non-destructive dry-run plans.
- API workflow adapters share the existing Automation workflow implementation;
  they do not introduce a competing set of project or delivery rules.
- `project.create` reports the effective artist selected by the shared project
  workflow.
- `revision.create` reports the effective revision description selected by the
  shared revision workflow.
- `intake.validate` can expose the provider-authored authoritative intake report
  content used by Studio.
- `delivery.create` exposes the authoritative delivery plan, including selected
  and excluded files, replacement mode, ZIP state, and clean-replacement
  deletion inventory required for Studio confirmation and reconciliation.

## Studio compatibility

JL Mixing Studio v1.1 is the coordinated consumer release for Automation v1.4.
Studio compatibility is governed by the reported Automation API version and
capabilities, not by matching application version numbers. v1.4.0 is the
provider release baseline used for coordinated Studio v1.1 acceptance.

## Compatibility

- Automation API version remains `1.0`.
- Workspace metadata remains on the existing v1.1 schema contract
  (`schema_version: 1.1.0`).
- Existing valid v1.1/v1.2/v1.3 workspaces remain supported.
- Existing human-facing commands remain supported.
- Application release version, Automation API version, and workspace metadata
  schema version remain independently versioned.

## Release-candidate testing

The `v1.4.0-rc.1` candidate is intended to be tested together with the
JL Mixing Studio v1.1 release candidate using the coordinated acceptance matrix
maintained in the Studio repository. RC fixes are limited to defects,
regressions, packaging failures, API-contract failures, and other release
blockers; new feature scope is deferred beyond this coordinated release.
