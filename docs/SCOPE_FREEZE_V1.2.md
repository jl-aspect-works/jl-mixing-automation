# JL Mixing Automation v1.2 Scope Freeze

**Status:** Approved and frozen, including approved metadata-version amendment
**Freeze date:** July 16, 2026
**Amendment date:** July 16, 2026
**Target release:** v1.2.0
**Authoritative baseline:** Latest released v1.1.1 source archive supplied for v1.2 development
**Baseline version:** `1.1.1`
**Baseline archive SHA-256:** `33b4de302beb5e6d6d8f9bd78b67a86eef976394fdf83dfbc88353e4af647065`

## 1. Scope-control rules

This document is the authoritative implementation boundary for JL Mixing
Automation v1.2.

The v1.1.1 archive identified above is the sole source baseline. Preserve all
existing v1.1 behavior, command compatibility, workspace compatibility, safety
checks, transaction behavior, schema identities, document structures, and output
conventions unless this scope freeze explicitly approves a change.

Implementation is limited to GitHub Issues #24, #31, #34, and #36 plus the
approved release/metadata version-independence amendment defined below.

During implementation:

- Change only code, tests, and documentation required by the approved scope.
- Prefer existing helpers and established code paths over new abstractions.
- Do not perform unrelated refactoring, cleanup, renaming, formatting passes,
  or behavior changes.
- Add clear explanatory comments to all new or materially changed code.
- Preserve existing error handling, validation, transaction, and rollback
  behavior except where an approved issue explicitly requires an adjustment.
- Do not change metadata schema identities, schema versions, document fields, or
  document structure. The approved `created_with` validation relaxation is the
  only schema-file change.
- Route any newly discovered user-visible behavior change, compatibility
  change, or additional defect back to design review before implementation.
- Treat pre-existing baseline defects separately; do not silently include them
  in v1.2 unless separately approved.

Every implementation must pass:

```text
ShellCheck
make test
make strict-test
make release-check
```

## 2. Included issues

### Issue #24 — Create the first revision during `new-mix`

#### Approved behavior

`new-mix` must create an unapproved initial revision as part of the existing
atomic project-creation transaction.

A newly created project must contain:

```text
04_Revisions/
└── Revision_01/
    └── Revision_Notes.md
```

Revision 1 must:

- use revision number `1`;
- use the fixed description `Initial mix`;
- have a newly generated valid revision UUID;
- use the existing `templates/Revision_Notes.md` template;
- use the existing canonical revision-manifest structure and helper logic where
  practical;
- have null approval fields; and
- be staged and committed with the rest of the new project.

The initial project manifest must have:

```json
{
  "state": {
    "current_revision": 1,
    "approved_revision": null,
    "delivered_revision": null
  }
}
```

The `revisions` array must contain exactly one canonical Revision 1 record. The
new project must derive to the existing `In progress` state rather than `Setup`.

#### Compatibility requirements

- `new-mix --description` remains the project creative-direction description.
- The project description does not become the Revision 1 description.
- `new-mix --source` continues importing original client delivery files into
  `01_Client_Files/Original_Delivery/`.
- Source files are not copied into Revision 1.
- `new-mix --cd` and shell integration continue entering the project root, not
  `Revision_01`.
- Dry-run remains fully non-mutating.
- Existing valid projects with `current_revision: 0` remain supported.
- `new-revision` continues creating Revision 1 for an existing zero-revision
  project.
- `new-revision` creates Revision 2 for a project created by v1.2 `new-mix`.
- No schema or migration changes are introduced.

#### Transaction requirements

Revision 1 creation must occur inside the current staged project transaction.
Any failure during revision UUID generation, notes rendering, manifest update,
validation, state validation, or final commit must leave no partial project.

#### Output requirements

Successful and dry-run output must report that the project starts with:

```text
Initial state:              In progress
Current revision:           1
Initial revision:           .../04_Revisions/Revision_01
```

The existing instruction to run the following command must be removed from the
new-project workflow:

```text
new-revision --description "Initial mix"
```

The next suggested lifecycle step may be `approve-mix`.

#### Required tests

Tests must verify at minimum:

- creation of `Revision_01/Revision_Notes.md`;
- absence of a revision `Prints/` subdirectory;
- expected Revision 1 heading and `Initial mix` description;
- `current_revision: 1`;
- null approved and delivered pointers;
- exactly one initial revision record;
- valid revision UUID and null approval fields;
- derived state `In progress`;
- correct dry-run reporting with no mutation;
- complete rollback after injected failure;
- removal of the obsolete `new-revision` next-step instruction;
- continued zero-revision project compatibility; and
- installed-command lifecycle behavior using the Revision 1 created by
  `new-mix`.

#### Out of scope

- A new initial-revision-description option
- Copying original source files into Revision 1
- Changing the `--cd` destination
- Migrating existing projects
- Refactoring unrelated revision or project-creation code

---

### Issue #31 — Derive the default artist from the client

#### Approved behavior

When `new-mix` is run without `--artist`, resolve the project artist in this
order:

1. Explicit nonempty `--artist`
2. Nonempty `client.defaults.artist`
3. `client.client_name`

An explicitly supplied empty artist remains an error:

```text
new-mix "Project Name" --artist ""
```

Do not silently replace an explicitly empty override with a client-derived
value.

#### Snapshot and manifest behavior

- `client-profile-snapshot.json` continues preserving the client configuration
  exactly as it existed.
- Do not populate or rewrite an empty `client.defaults.artist` in the snapshot.
- `project-manifest.json.artist` records the final resolved project artist.

#### Minimal implementation boundary

The functional change should remain limited to artist resolution in
`bin/new-mix`.

Do not change:

- `new-client` behavior;
- client, snapshot, or project schemas;
- existing client records;
- snapshot structure; or
- unrelated manifest generation.

#### Required tests

Tests must verify at minimum:

- explicit nonempty `--artist` has highest precedence;
- nonempty `client.defaults.artist` remains the normal default;
- empty `client.defaults.artist` falls back to `client.client_name`;
- explicit empty `--artist` is rejected;
- dry-run reports the resolved artist;
- invalid explicit artist input creates no project; and
- client snapshots are not rewritten with the resolved fallback.

#### Out of scope

- Modifying `client.json` automatically
- Requiring every client to configure an artist
- Adding schema defaults
- Migrating existing clients
- Refactoring unrelated client-resolution code

---

### Issue #34 — Support a positional project name in `new-mix`

#### Approved behavior

Support both command forms:

```text
new-mix "Project Name"
new-mix --project "Project Name"
```

The positional project name may appear before or after other valid options:

```text
new-mix "Blue Sky" --client acme
new-mix --client acme "Blue Sky"
new-mix --project "Blue Sky" --client acme
```

Both accepted forms must feed the same existing project-name validation and
creation path, including trimming, folder-name sanitization, project-ID
derivation, collision detection, manifest generation, transaction handling,
and rollback.

#### Invalid combinations

Supplying both project-name forms must fail before filesystem mutation:

```text
new-mix "Blue Sky" --project "Other Project"
new-mix --project "Blue Sky" "Other Project"
```

Recommended diagnostic:

```text
Project name cannot be specified both positionally and with --project.
```

Supplying more than one positional argument must also fail before mutation.
Recommended diagnostic:

```text
Unexpected positional argument: <argument>
```

The missing-project-name diagnostic must explain both supported forms, for
example:

```text
A project name is required. Supply it positionally or with --project.
```

#### Help requirements

The command synopsis must document both forms:

```text
Usage:
  new-mix PROJECT_NAME [options]
  new-mix --project PROJECT_NAME [options]
```

`--project` remains supported and is not deprecated.

#### Minimal implementation boundary

The production-code change should remain limited to argument parsing and help
text in `bin/new-mix`.

Do not change:

- schemas;
- manifest structure;
- project naming helpers;
- client resolution;
- transaction helpers;
- shell integration;
- installation layout; or
- argument parsing in other commands.

Do not tighten unrelated repeated-option behavior as part of this issue.

#### Required tests

Tests must verify at minimum:

- positional project name before options;
- positional project name after options;
- continued support for `--project`;
- equivalent project naming and paths from both forms;
- rejection when both forms are supplied, in either order;
- rejection of additional positional arguments;
- rejection of an empty positional name;
- no filesystem mutation after parse failure;
- updated help output; and
- continued operation of existing options with either form.

#### Out of scope

- Removing or deprecating `--project`
- Redesigning parsers for other commands
- Changing all generated `Next:` messages
- Tightening unrelated repeated-option handling
- Refactoring project naming or transaction code

---

### Issue #36 — Document ZIP creation with completed delivery notes

#### Approved behavior

This issue is a documentation and regression-test change only. Existing
production behavior is preserved.

The existing delivery-notes filename remains:

```text
05_Final_Delivery/Delivery_Notes.md
```

Do not rename it or add `release_notes.md`.

Document the supported workflow:

```text
create-delivery
# Edit 05_Final_Delivery/Delivery_Notes.md
create-delivery --zip --overwrite
```

The first command creates the editable delivery package. The user edits
`Delivery_Notes.md`, and the second command rebuilds the same package and
creates a ZIP containing the edited notes.

Documentation must explain that a one-step command:

```text
create-delivery --zip
```

naturally packages the clean notes template because the user has not yet had an
opportunity to edit it.

#### `--overwrite` limitation

Document that `--overwrite` requires the delivered path set to remain
unchanged. File contents may change, but adding, removing, or renaming delivered
paths causes the existing validation to reject overwrite.

If the path set changes, the user may need `--clean`. Because `--clean`
recreates the delivery folder and notes template, the user should preserve
edited notes before using it.

#### Required regression test

Extend the ZIP delivery integration test to perform the documented workflow:

```text
create-delivery
# Append recognizable text to Delivery_Notes.md
create-delivery --zip --overwrite
```

The test must verify at minimum:

- the ZIP exists;
- `Delivery_Notes.md` exists inside the ZIP;
- the extracted ZIP notes contain the edited text;
- the working delivery folder retains the edited notes;
- selected audio files remain present;
- the ZIP is not listed as a deliverable in `delivery-manifest.json`; and
- existing changed-path validation remains unchanged.

#### Minimal implementation boundary

No functional production-code change is approved for this issue.

Do not change:

- `bin/create-delivery` behavior;
- `tools/build-delivery.py` behavior;
- delivery schemas;
- delivery templates;
- delivery filenames;
- `--overwrite` path-set validation; or
- `--clean` behavior.

#### Out of scope

- Renaming `Delivery_Notes.md`
- Adding `release_notes.md`
- Pausing `create-delivery --zip` for user editing
- Automatically opening an editor
- Changing overwrite or clean semantics
- Refactoring delivery packaging code

### Approved scope amendment — Release and metadata version independence

#### Approved behavior

Application release versions and metadata schema versions are independent.
For v1.2.0:

```text
VERSION:                  1.2.0
metadata.schema_version:  1.1.0
metadata.created_with:    jl-mixing 1.2.0
```

`metadata.schema_version` continues identifying the unchanged v1.1 document
contract. `metadata.created_with` continues recording the application release
that originally created a document, but readers must validate it only as an
exact semantic JL Mixing release identifier. It must not be required to match
the schema major/minor series.

Existing documents created by v1.1 releases remain valid. New documents created
by v1.2 record `jl-mixing 1.2.0` while retaining `schema_version: 1.1.0`.
Mutable documents retain their original immutable `created_with` value when
subsequently edited by another release.

#### Required implementation

- Set the repository `VERSION` file to `1.2.0`.
- Remove application guards that require the release version to be `1.1.x`.
- Validate the application `VERSION` as an exact three-component semantic
  version.
- Validate `metadata.created_with` as `jl-mixing X.Y.Z`, independently from
  `metadata.schema_version`.
- Relax the five v1.1 schema files only enough to accept semantic JL Mixing
  release provenance from any release series.
- Preserve every schema `$id`, title, `schema_version` constant, required field,
  and document structure.
- Update project-state validation and release-package checks consistently.
- Publish the v1.2 release using `docs/RELEASE_NOTES_V1.2.md`.

#### Compatibility requirements

- No workspace migration is required.
- Existing v1.1-created studio, client, project, snapshot, and delivery records
  remain valid without modification.
- Schema compatibility remains governed exclusively by `metadata.schema` and
  `metadata.schema_version`.
- `created_with` remains provenance and must not be rewritten during normal
  mutable-document updates.
- The legacy shell helper name `jl_json_require_created_with_series` should
  remain as a compatibility alias even though series matching is removed.

#### Required tests

Tests must verify at minimum:

- v1.2-generated records use `schema_version: 1.1.0`;
- v1.2-generated records use `created_with: jl-mixing 1.2.0`;
- valid v1.1 and v1.2 creator releases are both accepted with the v1.1 schema;
- malformed creator release identifiers are rejected;
- malformed application `VERSION` values are rejected;
- installed and release-archive commands preserve the same separation; and
- release automation publishes the v1.2 release notes.

#### Out of scope

- Changing any metadata schema version from `1.1.0`
- Adding or removing metadata fields
- Rewriting existing records to change `created_with`
- Introducing migration logic
- Supporting prerelease or build-metadata suffixes in `VERSION`
- General schema refactoring or consolidation

## 3. Expected minimal change footprint

The expected affected files are limited primarily to:

### Production code and release metadata

- `VERSION`
- `bin/new-mix` and the release-provenance capture in `bin/create-delivery`
- the release-series guards in `bin/new-studio` and `bin/new-client`
- `lib/metadata.sh`, `lib/json.sh`, and directly affected context validation
- `tools/project-state.py`
- `tools/build-release`, `tools/release-check`, and `tools/verify-release-archive`
- the five v1.1 JSON schema files, limited to the `created_with` pattern
- `.github/workflows/release.yml`

Issue #36 itself introduces no functional delivery change. The only
`create-delivery` edit is the approved release-provenance capture required by
the metadata-version amendment. `new-revision`, delivery building, metadata
schema identities, and document structures remain unchanged.

### Tests

Likely affected tests include:

- `tests/integration/test-new-mix.sh`
- `tests/integration/test-new-revision.sh`
- `tests/integration/test-create-delivery-zip.sh`
- relevant installation lifecycle tests

Changes to other tests must be directly justified by an approved behavior.

### Documentation

Update only documentation affected by the approved workflows, likely including:

- `README.md`
- `docs/USER_GUIDE.md`
- `docs/SCRIPT_REFERENCE.md`
- v1.2 release notes or changelog content

Avoid broad documentation rewrites.

## 4. Explicitly excluded from v1.2

The following are not part of the frozen v1.2 scope:

- Any GitHub issue other than #24, #31, #34, and #36
- Expanded intake validation or audio QC
- `ffmpeg` full-file decode validation
- SHA-256 intake duplicate detection
- Dual-mono detection
- Archive or reactivation commands
- Workspace migration or upgrade handling
- Metadata schema-version or document-structure revisions
- Changes to delivery packaging behavior beyond the Issue #36 regression test
- Automatic generation or redesign of the repository `VERSION` file; only
  setting its release value to `1.2.0` is approved
- New DAW metadata, template, or preset management
- Project lifecycle directory changes
- Unrelated bug fixes, refactoring, formatting, or cleanup

## 5. Implementation sequencing

To minimize risk and keep reviews focused, implement in this order unless a
specific dependency requires otherwise:

1. Issue #31 — artist fallback
2. Issue #34 — positional project name
3. Issue #24 — initial revision creation
4. Issue #36 — documentation and ZIP regression test
5. Release/metadata version-independence amendment
6. Consolidated documentation and release notes
7. Full quality-gate and release-package verification

Each issue should be reviewable as a focused change. Shared edits to
`bin/new-mix` may be combined only when doing so keeps behavior and tests clear
and does not introduce unrelated refactoring.

## 6. Definition of done

JL Mixing Automation v1.2 scope is complete only when:

- all four approved issues and the approved metadata-version amendment meet
  the behavior and compatibility requirements in this document;
- all required focused tests are present and passing;
- existing v1.1.1 behavior remains compatible except for the explicitly
  approved changes;
- no unapproved schema-version, document-structure, migration, command, or
  workflow changes are present;
- new and materially changed code contains clear explanatory comments;
- ShellCheck passes;
- `make test` passes;
- `make strict-test` passes;
- `make release-check` passes;
- release documentation accurately describes the implemented behavior; and
- the final diff has been reviewed for unrelated changes.

Any change to this frozen scope requires explicit approval and an update to
this document before implementation.
