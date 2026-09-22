# JL Mixing Automation v2.1 User Guide

JL Mixing Automation is the workflow engine behind JL Mixing Studio. Most daily
workflow can be performed from Studio, while the human CLI remains available for
direct automation use and recovery/administrative workflows.

Automation v2.1 continues using Automation API `1.0` and workspace metadata
schema `1.1.0`.

## 1. Create the workspace

```text
new-studio
```

The default root is `~/Music/Mixes/`. Use `--default-cd` if creation commands
should enter newly created directories automatically. `--cd` and `--no-cd`
override that preference for an individual command.

After creation, Studio can edit supported Studio defaults through Automation's
authoritative update capability rather than editing `studio.json` directly.

## 2. Create and maintain clients

```text
new-client acme --name "Acme Records"
```

`new-client` may be run from anywhere. Studio-root resolution uses:

1. `--root PATH`
2. `JL_MIXING_ROOT`
3. current-directory studio context
4. `~/Music/Mixes`

A client contains `client.json` and a flattened `Projects/` directory. Audio and
delivery defaults are inherited from `studio.json` unless overridden. An artist
default is optional.

Studio v2.1 can edit supported client metadata through Automation's managed
client-update operation. Automation remains authoritative for validation,
conflict checks, and persistence.

## 3. Create and maintain a project

From a client directory or with an explicit client reference:

```text
new-mix "Blue Sky"
new-mix "Blue Sky" --client acme
```

The equivalent `--project "Blue Sky"` form remains supported. When `--artist`
is omitted, the project uses the nonempty `client.defaults.artist` value and
then the client's display name.

`new-mix` creates `04_Revisions/Revision_01/Revision_Notes.md` with the initial
revision description. Use `--source PATH` to copy an initial client delivery into
`01_Client_Files/Original_Delivery/`. Source material is copied, never moved or
modified.

Studio v2.1 can edit supported project metadata through Automation's managed
project-update operation.

## 4. Manage Client Files and validate intake

```text
validate-intake
```

Validation is non-destructive to `01_Client_Files/Original_Delivery/`. The
managed intake report can include:

- file inventory and channel counts
- project-format mismatches
- exact SHA-256 duplicate detection
- corrupt/unreadable-file findings
- `ffprobe` metadata inspection when available
- full-file decode integrity checks through `ffmpeg` when available
- exact dual-mono warnings for stereo files with identical channels
- skipped checks and preparation recommendations

Unavailable external inspection tools are reported as skipped. JL Mixing does
not automatically convert, repair, rename, move, or delete original client
files.

### Managed Client Files import

Studio v2.1 can import additional Client Files through Automation's managed
plan/execute workflow. Before files are copied, Studio shows conflicts and lets
the user choose Add or Skip per file, or apply Add All / Skip All. Automation
revalidates the selected plan before execution and preserves path-safety and
transactional behavior.

Client Files validation findings remain visible on the Client Files screen, but
they do not by themselves put the overall project into Needs Attention. Project
validation attention is driven by Audio Prep / Audio Files readiness.

## 5. Prepare working audio

Accepted working files live under:

```text
02_Audio_Preparation/Working_Audio/
```

Automation provides structured Audio Prep validation and provenance information
used by Studio. Studio v2.1 also exposes a managed Audio Prep reset workflow that
rebuilds the managed working set from the current Client Files source through an
authoritative Automation plan/execute operation.

Reset is intentionally managed rather than an unrestricted filesystem delete or
copy operation.

## 6. Work with revisions

Place initial mix prints in:

```text
04_Revisions/Revision_01/
```

When another revision is needed:

```text
new-revision --description "Client notes addressed"
```

Use `--source FILE_OR_DIRECTORY` to copy immediate mix-print files into the new
revision directory.

### Close and reopen revisions

Studio v2.1 adds reversible Close/Reopen controls backed by Automation. Use
Close when a revision was created by mistake, abandoned, or should no longer be
treated as the active/current revision. Closing does not delete revision files or
history. Reopen restores the revision to the normal workflow when needed.

This avoids destructive revision deletion while allowing project health to
reflect the revision that is actually being worked on.

## 7. Approve and unapprove a revision

```text
approve-mix
```

The current revision is approved by default. An older existing revision can be
selected explicitly:

```text
approve-mix --revision 2 --approved-by "Client"
```

Approval updates project metadata only. It does not alter revision files or an
existing final-delivery package.

Studio v2.1 can also Unapprove an approved revision through Automation. This is
a reversible metadata operation and does not remove revision files or delivery
history.

## 8. Create final delivery

```text
create-delivery
```

The command packages the approved revision, considering immediate regular files
except `Revision_Notes.md`. `--include`, `--exclude`, and `--working-prefix`
control selection. Copied files are SHA-256 verified and recorded in the delivery
manifest.

### ZIP workflow

To include edited delivery notes in a ZIP:

```text
create-delivery
# Edit 05_Final_Delivery/Delivery_Notes.md
create-delivery --zip --overwrite
```

Generated ZIP names use:

```text
<project-id>-rev-<NN>-<YYYYMMDDHHMMSS>.zip
```

### Replacing a delivery

```text
create-delivery --overwrite
```

`--overwrite` is for same-shape replacement and requires the delivered path set
to remain unchanged.

```text
create-delivery --clean
```

`--clean` replaces generated Delivery contents according to the managed delivery
plan. Review `create-delivery --dry-run --clean` before using it.

Studio uses Automation's managed Delivery status and reconciliation operations to
show whether a package is current, stale, missing, or ready to build.

## 9. Studio / Automation API integration

JL Mixing Studio and other machine clients discover Automation with:

```text
jl-mixing system-info --json
```

Automation API `1.0` uses additive capability discovery. Studio v2.1 relies on
capability-backed operations for:

- Studio, client, and project metadata updates
- cached structured intake validation
- managed Client Files import, including selected-file execution
- Audio Prep validation, provenance, and managed reset
- revision creation and description updates
- revision Close/Reopen
- approval and Unapprove
- Delivery status, reconciliation, package creation, and managed cleanup
- system/version/capability discovery

Machine clients must use the reported `api_version` and `capabilities` rather
than parsing human CLI output or assuming compatibility from the product release
number.

## Directory layout

```text
~/Music/Mixes/
├── Studio/studio.json
└── Clients/<Client>/
    ├── client.json
    └── Projects/<Project>/
        ├── 00_Admin/
        ├── 01_Client_Files/
        ├── 02_Audio_Preparation/
        ├── 03_DAW_Project/
        ├── 04_Revisions/Revision_NN/
        ├── 05_Final_Delivery/
        └── 06_Recall/
```

`03_DAW_Project/` is opaque user/DAW-owned content. JL Mixing creates the
boundary but does not interpret or manage native DAW project files.

## Compatibility

Automation v2.1 continues using metadata schema `1.1.0` and Automation API
`1.0`. Existing valid v1.1+ workspaces remain compatible; no workspace migration
is introduced by v2.1. Application release, Automation API, and metadata schema
versions remain independent contracts.
