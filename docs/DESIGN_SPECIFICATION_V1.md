# JL Mixing Automation v1.1 Design Summary

The detailed approved design is in `V1.1_DESIGN_SPEC.md`,
`V1.1_COMMAND_CONTRACTS.md`, and `V1.1_DATA_MODEL.md`. This document is the
compact runtime-oriented summary.

## Workspace

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
        ├── 04_Revisions/
        ├── 05_Final_Delivery/
        └── 06_Recall/
```

Project paths are stable. Lifecycle is represented by revision pointers, not by
moving projects between directories.

## State model

```json
{
  "current_revision": 3,
  "approved_revision": 2,
  "delivered_revision": 2
}
```

- Setup: no revisions
- In progress: current and approved revisions differ
- Approved: current equals approved and is not the current delivery
- Delivered: current, approved, and delivered pointers agree and the delivery
  manifest is structurally valid

Revision status is derived as `open`, `approved`, or `superseded`; it is not
stored in revision records.

## Ownership boundaries

- JL-managed: JSON manifests and generated delivery files
- User-managed: project, preparation, revision, delivery, and recall Markdown
- Shared: only the automated section in `Intake_Report.md`
- Immutable: `Original_Delivery/`
- Opaque: `03_DAW_Project/`

Automation never silently deletes user-owned content, except when the user
explicitly authorizes the fully destructive `create-delivery --clean` operation
within `05_Final_Delivery/`.

## Delivery

The approved revision is the only delivery source. Selected regular files are
copied without extension restrictions, verified with SHA-256, and recorded in
an immutable delivery manifest. Filename classification is optional and uses
`unclassified` when no recognized phrase matches.

## Compatibility

v1.1 operates only on exact v1.1 schemas and rejects recognizable v1.0 layouts.
There is no migration or automatic repair.
