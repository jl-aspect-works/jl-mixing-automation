# JL Mixing Automation Roadmap

**Status:** Living, version-agnostic backlog guidance

## Product role

JL Mixing Automation is the stable workflow engine and CLI for the JL Mixing
ecosystem. It owns project structure, metadata validation, lifecycle rules,
filesystem mutation, delivery behavior, and the public machine-readable
Automation API.

## Versioning

The Automation application version, Automation API version, and metadata schema
version are independent. Application releases may retain the same API and schema
versions when those contracts do not change.

The current v1.5 line uses:

- Automation API `1.0`
- workspace metadata schema `1.1.0`
- one authoritative cross-platform Python implementation

## Current release priority

Complete v1.5 cross-platform acceptance on macOS and Windows while preserving
existing CLI/API/workspace compatibility. RC findings should be fixed before the
stable release when they materially affect supported behavior.

## Future-feature policy

Future work is maintained as a version-agnostic backlog until a specific release
scope is explicitly approved. Do not assign proposed features to product versions
merely because they are discussed or captured as issues.

Candidate areas include:

- delivery-workflow usability and note-preservation semantics
- native one-click Windows/macOS installers
- project archive/restore design
- additional intake-QC capabilities
- structured inspection/health operations
- batch operations with explicitly designed transaction semantics

GitHub issues are the source of truth for the detailed design and readiness of
these items.

## Metadata policy

Metadata changes are the slowest-moving track. Add persisted fields only when the
information must travel with the workspace and be understood by Automation,
Studio, or another supported client. UI preferences, recent items, favorites,
search history, and rebuildable indexes do not belong in project schemas.

## API policy

Automation API capabilities are advertised only when the structured operation,
response envelope, schema/examples, parity tests, and packaging/install behavior
are implemented. Machine clients use capability discovery instead of product
version matching.

## Release admission rule

A feature is assigned to an Automation release only after its behavior, API
impact, schema impact, compatibility requirements, tests, and Studio dependency
are reviewed and explicitly approved. Cross-repository features use linked issues
rather than a single mixed implementation issue.

## Non-goals

Automation does not own desktop presentation, local UI preferences,
general-purpose indexing, cloud collaboration, accounting, CRM, or DAW session
processing.
