# JL Mixing Automation API

**Status:** API 1.0 discovery implemented; workflow operations pending
**Initial target:** API 1.0

## Purpose

The Automation API is the stable machine contract used by JL Mixing Studio and future supported clients. It does not replace the human-oriented CLI. Existing commands remain usable interactively while supported machine operations gain documented JSON behavior.

## Transition baseline

JL Mixing Studio 1.0 depends on the exact JL Mixing Automation 1.3.0 command contract. API 1.0 will be introduced explicitly; no current command output should be described as API 1.0 until implementation and contract tests are released.

## Dispatcher and version discovery

`jl-mixing` is the canonical machine-facing Automation API dispatcher. JL Mixing Studio and future supported API clients invoke only this executable with allowlisted subcommands and arguments.

Existing human-facing commands such as `new-client`, `new-mix`, `validate-intake`, `new-revision`, `approve-mix`, and `create-delivery` remain supported. The dispatcher and existing commands share the same underlying implementation; the dispatcher must not invoke the existing commands as subprocesses or create a competing implementation of workflow rules.

Machine-readable discovery uses:

```bash
jl-mixing system-info --json
```

Example response:

```json
{
  "api_version": "1.0",
  "application": {
    "name": "jl-mixing",
    "version": "1.4.0"
  },
  "metadata": {
    "readable_schema_versions": ["1.1.0"],
    "writable_schema_version": "1.1.0"
  },
  "capabilities": [
    "client.create",
    "project.create",
    "intake.validate",
    "revision.create",
    "revision.approve",
    "delivery.create"
  ]
}
```

## Response envelope

Every API operation returns one JSON object on standard output:

```json
{
  "api_version": "1.0",
  "operation": "project.create",
  "status": "success",
  "data": {},
  "warnings": [],
  "errors": []
}
```

Required top-level fields are `api_version`, `operation`, `status`, `data`, `warnings`, and `errors`.

Allowed status values for API 1.0 are:

- `success` — operation completed and authoritative state was committed;
- `planned` — dry-run completed without mutation;
- `blocked` — request was understood but governing state or findings prevented completion;
- `error` — request could not be completed because of invalid input, environment, transport, or internal failure.

## Error objects

Errors use stable machine codes and human-readable messages:

```json
{
  "code": "PROJECT_NOT_FOUND",
  "message": "The requested project could not be resolved.",
  "details": {},
  "retryable": false
}
```

Clients must branch on `code`, not message text.

## Exit-code contract

Automation API 1.0 preserves the existing JL Mixing Automation exit-code contract:

| Exit code | Meaning | JSON status |
|---:|---|---|
| `0` | Successful operation or valid dry-run preview | `success` or `planned` |
| `1` | General or internal failure | `error` |
| `2` | Invalid arguments or request | `error` |
| `3` | Configuration or required-tool problem | `error` |
| `4` | Workspace, client, project, or execution-context problem | `error` |
| `5` | Validation completed with blocking findings | `blocked` |
| `6` | Unsafe operation rejected | `blocked` |

The JSON `status` describes the broad outcome, while stable machine error codes describe the specific reason. Clients should branch primarily on JSON status and machine codes and use the process exit code as a secondary integrity check and for shell compatibility.

A valid dry run returns `status: planned` with exit `0`. Intake validation that completes and writes a valid report but finds blocking issues returns `status: blocked` with exit `5`. Safety guardrail rejections return `status: blocked` with exit `6`.

Failures outside the running API contract retain operating-system conventions. A missing executable may produce shell exit `127`, and signal termination may produce `128 + signal`. Missing or malformed JSON is always treated by clients as an Automation transport or protocol failure regardless of process exit code.

## Compatibility rules

Within API major version 1:

- new optional fields and capabilities may be added;
- existing required fields and field meanings must not change;
- operation identifiers and documented status meanings must remain stable;
- clients must ignore unknown optional fields;
- removed or incompatible behavior requires API 2.0.

The Automation application version may change without changing the API version.

## Capability discovery

Studio shall use capability identifiers for optional features. A missing optional capability disables only that feature. Missing required capabilities make the installed Automation version incompatible with that Studio release.

Capability names use stable dotted identifiers. Initial candidates include:

- `system.info`
- `studio.create`
- `client.create`
- `project.create`
- `intake.validate`
- `revision.create`
- `revision.approve`
- `delivery.create`

## Dry-run contract

Mutating operations that support preview return `status: planned` and a structured plan. The confirmed operation must identify the same logical request. Clients must still re-read authoritative workspace state after success; JSON output does not replace post-operation reconciliation.

## Read-only query scope

Automation API 1.0 includes system and capability discovery but does not include general read-only workspace, client, project, revision, report, or delivery query operations.

General read-only queries are targeted for a backward-compatible API 1.1 addition after their normalized response models, partial-failure behavior, filtering and ordering rules, path-exposure policy, and Studio migration plan are designed. The first design should evaluate a normalized workspace snapshot operation before introducing many small query commands.

Until Studio adopts those future capabilities, it may continue reading and validating authoritative workspace files directly.

## Progress-event contract

Long-running API operations may support opt-in machine-readable progress through:

```bash
jl-mixing intake validate --json --progress=json
```

The streams have separate contracts:

- standard output contains exactly one final Automation API response;
- standard error contains zero or more newline-delimited JSON progress-event objects.

When `--progress=json` is enabled, every non-empty standard-error line must be a valid progress event. Human-formatted diagnostics must not be mixed into that stream.

Example progress event:

```json
{
  "api_version": "1.0",
  "event": "progress",
  "operation": "intake.validate",
  "phase": "inspection",
  "completed": 3,
  "total": 12,
  "unit": "files",
  "message": "Inspecting audio files."
}
```

Progress is advisory. Events do not prove that a mutation committed, a report was written, or authoritative state matches the request. The final response, exit code, and client reconciliation remain authoritative.

Operations report `completed`, `total`, and `unit` only when the total is known reliably. Clients use indeterminate progress when these values are absent. Published phase identifiers become stable API values; initial candidates include `discovery`, `validation`, `inspection`, `copy`, `verification`, `archive`, `report`, and `commit`.

Progress support is optional by capability and operation. Cancellation semantics are not part of API 1.0 and require a separate design.

### Audio Prep reset progress

When `system-info` advertises `audio.prep.reset.progress`, callers may add
`--progress=stderr-json` to `audio-prep reset-execute`. Each stderr line prefixed
with `JL_PROGRESS ` contains JSON with operation `audio.prep.reset.execute`,
phase (`planning`, `staging`, `importing`, `finalizing`, or `complete`),
`completed`, `total`, `overall_completed`, `overall_total`, and `active` paths.
The initial planning event has no total. Later events use engine-reported
source-file counts and monotonically increasing overall steps. The terminal
`complete` event is emitted only after execution and lineage recording return
successfully. The final stdout response remains authoritative; a failed or
rolled-back reset never emits the terminal completion event. Without the
capability, clients should omit the flag and show indeterminate execution.

## JSON Schema publication

Automation API schemas use JSON Schema Draft 2020-12 and remain distinct from persisted workspace metadata schemas.

The authoritative development layout is:

```text
api/
├── schemas/
│   └── v1.0/
│       ├── response-envelope.schema.json
│       ├── error.schema.json
│       ├── warning.schema.json
│       ├── progress-event.schema.json
│       ├── system-info.schema.json
│       └── operations/
└── examples/
    └── v1.0/
        ├── success/
        ├── planned/
        ├── blocked/
        └── error/
```

Schemas and golden examples in the JL Mixing Automation repository are the reviewed source of truth. Every Automation release supporting API 1.0 bundles the applicable schemas and examples for offline use under its installed shared-data directory. `system-info` reports the installed schema location explicitly.

Released schemas are also published at immutable API-versioned GitHub Pages URLs such as:

```text
https://jlaudio.github.io/jl-mixing/api/v1.0/schemas/response-envelope.schema.json
```

Those public URLs are the canonical `$id` values. They contain the Automation API version, not the Automation application release version.

Published API-version directories must not be replaced with incompatible content. New backward-compatible capabilities may add schema files within API 1.x; incompatible contract changes require a new API major version.

JL Mixing Studio vendors or pins the supported schemas at build time and must not depend on downloading them at runtime.

## Output and process rules

- JSON mode writes only the response object to standard output.
- Human diagnostics may use standard error when progress JSON mode is not enabled and the behavior is documented.
- When `--progress=json` is enabled, standard error contains only newline-delimited JSON progress events.
- Commands remain non-interactive in JSON mode.
- Paths are returned as explicit fields, never embedded only in prose.
- Exit codes must agree with the JSON status and the approved mapping.
- Secrets and unrestricted command strings are never returned.

## Contract testing

API releases shall include:

- JSON Schema validation for every response and progress-event type;
- golden success, planned, blocked, and error examples;
- compatibility tests proving older API 1.x clients can ignore newly added optional fields;
- tests for paths containing spaces and non-destructive dry-run behavior;
- exact tests for operation identifiers, machine error codes, and exit-code mapping;
- progress tests proving stdout remains a single final object and progress-mode stderr contains only valid newline-delimited event objects;
- packaging tests proving the released schemas and examples are installed with Automation;
- publication checks proving each released schema `$id` matches its immutable API-versioned public URL;
- parity tests proving dispatcher operations and corresponding human-facing commands use the same workflow rules and produce equivalent authoritative state.

## Approved design decisions

1. `jl-mixing` is the canonical machine-facing API dispatcher. Existing human-facing commands remain supported and share the same underlying implementation.
2. API 1.0 preserves existing exit codes `0` through `6`: exit `0` maps to `success` or `planned`; exits `1` through `4` map to `error`; exits `5` and `6` map to `blocked`. Stable JSON machine codes provide the specific reason.
3. API 1.0 supports opt-in progress events through `--progress=json`. Events are newline-delimited JSON on standard error, while standard output remains one final response. Progress is advisory and does not replace final-response or authoritative-state reconciliation.
4. API 1.0 does not include general read-only queries beyond system and capability discovery. General workspace and domain queries are targeted for a backward-compatible API 1.1 addition after their contracts and Studio migration plan are designed.
5. API schemas use JSON Schema Draft 2020-12, live under `api/schemas/<api-version>/`, ship with Automation releases for offline use, and are published at immutable API-versioned GitHub Pages URLs used as canonical `$id` values. Studio vendors or pins schemas at build time and does not download them at runtime.

All API 1.0 design decisions required by this document are approved. Implementation scope still requires a separate release plan and approved implementation issues.
