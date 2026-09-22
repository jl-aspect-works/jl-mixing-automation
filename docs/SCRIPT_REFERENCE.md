# JL Mixing Automation v1.5 Command Reference

Every human-facing command supports `-h` and `--help`. Mutating commands validate
workspace metadata and filesystem boundaries before committing changes.

## `jl-mixing`

```text
jl-mixing system-info --json
jl-mixing --help
```

`jl-mixing` is the canonical machine-facing Automation API dispatcher.
`system-info --json` reports the Automation API version, application release,
metadata schema compatibility, capabilities, and installed API schema location.

API clients must use `api_version` and `capabilities`, not the application
release number, to determine compatibility.

## `new-studio`

```text
new-studio [--root PATH] [--name NAME] [--engineer NAME]
           [--sample-rate HZ] [--bit-depth BITS]
           [--file-format WAV|AIFF]
           [--default-cd|--no-default-cd] [--dry-run]
```

Creates a new workspace. The default root is `~/Music/Mixes/`.

## `new-client`

```text
new-client CLIENT_ID [--name NAME] [--artist NAME]
           [--sample-rate HZ] [--bit-depth BITS]
           [--file-format WAV|AIFF] [--delivery-method TEXT]
           [--deliverables LIST] [--root PATH]
           [--cd|--no-cd] [--dry-run]
```

Creates `Clients/<Readable Name>/client.json` and `Projects/`.

Studio-root resolution order is:

1. explicit `--root PATH`
2. `JL_MIXING_ROOT`
3. current-directory studio context
4. default `~/Music/Mixes` workspace

This allows studio-level client creation from an unrelated working directory.

## `new-mix`

```text
new-mix PROJECT_NAME [options]
new-mix --project PROJECT_NAME [options]

Options include:
  --client ID_OR_PATH  --project-id ID  --artist NAME
  --album TITLE        --producer NAME  --engineer NAME
  --bpm NUMBER         --key TEXT       --time-signature TEXT
  --sample-rate HZ     --bit-depth BITS --file-format WAV|AIFF
  --deadline YYYY-MM-DD                  --deliverables LIST
  --description TEXT   --source PATH    --cd|--no-cd  --dry-run
```

Creates the complete project tree, project manifest, client-profile snapshot,
and unapproved Revision 1 transactionally. Artist precedence is explicit
`--artist`, client artist default, then client display name.

## `validate-intake`

```text
validate-intake [--project PATH] [--source PATH]
                [--expected-sample-rate HZ]
                [--expected-bit-depth BITS]
                [--no-duplicate-check] [--dry-run]
```

Validation is read-only with respect to original client files. The managed report
can include metadata, decode-integrity results, exact SHA-256 duplicates,
project-format mismatches, channel counts, exact dual-mono warnings, unsupported
or unreadable files, skipped checks, and preparation recommendations.

`ffprobe` and `ffmpeg` are used when available for enhanced checks. Missing
external inspection tools produce explicit skipped-check reporting.

## `new-revision`

```text
new-revision [--project PATH] [--description TEXT]
             [--source PATH] [--cd|--no-cd] [--dry-run]
```

Creates the next contiguous `Revision_NN/` directory and advances
`state.current_revision` transactionally.

## `approve-mix`

```text
approve-mix [--project PATH] [--revision NUMBER]
            [--approved-by NAME] [--date TIMESTAMP] [--dry-run]
```

Approves the current revision by default. Approval may move to another existing
revision and does not modify revision files or final-delivery content.

## `create-delivery`

```text
create-delivery [--project PATH] [--include PATTERN]
                [--exclude PATTERN] [--working-prefix TEXT]
                [--overwrite|--clean] [--zip] [--dry-run]
```

Packages the approved revision, verifies copied bytes with SHA-256, writes the
delivery manifest, and updates `state.delivered_revision` transactionally.

For a ZIP containing edited delivery notes:

```text
create-delivery
edit 05_Final_Delivery/Delivery_Notes.md
create-delivery --zip --overwrite
```

`--overwrite` requires an unchanged delivered path set. `--clean` replaces all
contents inside `05_Final_Delivery/`; review `--dry-run --clean` before using it.

Generated ZIPs use:

```text
<project-id>-rev-<NN>-<YYYYMMDDHHMMSS>.zip
```

## Automation API 1.0 capabilities

v1.5 advertises these capability names through `system-info`:

```text
client.create
delivery.create
intake.validate
intake.validate.report
project.create
project.create.artist
revision.approve
revision.create
revision.create.description
system.info
```

The API schemas under `api/schemas/v1.0/` govern machine request/response
contracts. Human CLI output is not a machine API contract.

## Removed legacy interface

v1.5 retains the v1.1 removal of the project-completion command and other retired
v1.0 options. Known removed flags are rejected with explicit diagnostics rather
than silently ignored.
