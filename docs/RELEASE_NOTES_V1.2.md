# JL Mixing Automation v1.2.0 Release Notes

JL Mixing Automation v1.2 is a focused workflow release built on the v1.1.1
code and v1.1 workspace schemas. It preserves existing v1.1 behavior except for
the four approved workflow changes and the metadata-version correction below.

## Highlights

- `new-mix` creates an unapproved `Revision_01` and rendered
  `Revision_Notes.md` as part of the atomic project transaction.
- `new-mix` accepts either `new-mix PROJECT_NAME` or
  `new-mix --project PROJECT_NAME`.
- When `--artist` is omitted, the project artist resolves from the client artist
  default and then the client display name.
- The documented ZIP workflow now preserves completed delivery notes:
  `create-delivery`, edit `Delivery_Notes.md`, then
  `create-delivery --zip --overwrite`.
- Application release versioning is now independent from metadata schema
  versioning: v1.2 records `created_with: jl-mixing 1.2.0` while retaining the
  unchanged `schema_version: 1.1.0` document contract.

## Compatibility

v1.2 continues using the exact v1.1.0 JSON schema identities and document
structures and supports existing valid v1.1 workspaces. The `created_with`
validation constraint is relaxed so application provenance is independent of
the schema version. It does not migrate v1.0 workspaces and does not change
delivery packaging, intake validation, metadata fields, or DAW ownership.

## Normal project workflow

```text
new-studio → new-client → new-mix (creates Revision_01)
→ validate-intake → manual mix/review → approve-mix → create-delivery
```

Use `new-revision` when another revision is needed after Revision 1.
