# JL Mixing Automation v1.1.0 Release Notes


## v1.1.1

### Fixed

- Fixed automatic directory changes on macOS when `TMPDIR` ends with `/`.
- Prevented doubled-slash temporary paths such as `.../T//jl-mixing-cd...`.
- Restored `--cd` behavior for `new-client`, `new-mix`, and `new-revision`.

### Compatibility

- No workspace-schema changes.
- No command-interface changes.
- Existing v1.1.0 workspaces remain compatible.


## v1.1.0

## Highlights

- Projects now live directly beneath `Clients/<Client>/Projects/` and retain a
  stable path throughout the workflow.
- JL Mixing no longer manages DAW templates, presets, or DAW-specific metadata.
- Revision workflow uses explicit current, approved, and delivered pointers.
- Final delivery copies are verified with SHA-256 and recorded in a strict,
  immutable delivery manifest.
- Studios can keep their own naming conventions; unmatched deliverables are
  classified as `unclassified` rather than rejected.
- Creation commands can enter the newly created directory automatically through
  installer-managed bash/zsh integration.
- Installation, upgrades, shell configuration, and uninstall are transactional.

## Breaking changes

- v1.1 requires a fresh workspace and does not migrate v1.0 data.
- Project completion and reactivation are removed.
- `Active/`, `Completed/`, DAW resource directories, nested DAW project folders,
  and revision `Prints/` directories are removed.
- Several v1.0 options are rejected with migration diagnostics.

## Intake validation

The v1.0.4 `validate-intake` behavior is preserved, including opportunistic
`ffprobe` metadata and duplicate-basename detection. Expanded decoding, exact
content duplicate detection, dual-mono detection, and deeper QC remain future
work.

## Delivery safety

`create-delivery --overwrite` supports same-shape replacement while preserving
unrelated content. `create-delivery --clean` is intentionally destructive and
replaces every item inside `05_Final_Delivery/`, with rollback protection if the
new package cannot commit.
