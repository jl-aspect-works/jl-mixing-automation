# Automation API `delivery.create`

`delivery.create` exposes the existing `create-delivery` workflow through the Automation API 1.0 dispatcher without invoking the human-facing command as a subprocess.

## Command

```bash
jl-mixing delivery create --json --project PATH [options]
```

Supported delivery options mirror `create-delivery`, including `--include`, `--exclude`, `--working-prefix`, `--overwrite`, `--clean`, `--zip`, and `--dry-run`.

JSON mode requires an explicit `--project PATH` so clients do not depend on shell working-directory context.

## Results

The response uses the common API 1.0 envelope. Successful and planned responses identify the project, approved revision, project manifest, delivery folder, delivery notes, delivery manifest, replacement mode, workspace, and ZIP request state. Successful ZIP creation also reports the generated archive path.

Automation API 1.0 additionally exposes the authoritative delivery plan used by the shared workflow so GUI consumers do not need to parse human-facing output. The structured data includes:

- project name and identity
- current, approved, and delivered revision state
- delivery method
- selected deliverables with source name, deliverable type, and destination path
- excluded files with exclusion reason
- clean-replacement deletion inventory
- ZIP name/path when requested

A dry run returns `status: planned` and does not mutate the delivery folder or project manifest. For `--clean`, its `deletions` array is the exact validated inventory the workflow plans to remove, allowing consumers to require explicit confirmation without reconstructing the plan themselves.

Completed delivery creation returns `status: success`. Validation or safety guardrails return `blocked` with stable machine-readable error codes while preserving the existing Automation exit-code contract.

## Authoritative state

Clients must re-read the project manifest and generated delivery artifacts after success. The JSON response describes the operation result but does not replace authoritative workspace state.

The API and `create-delivery` share the same in-process implementation, including approved-revision selection, file filtering/classification, checksum verification, ZIP handling, replacement guardrails, delivery notes behavior, and project manifest updates. The machine-facing plan fields are emitted from the same validated `plan.json` consumed by delivery execution; they are not reconstructed from human CLI text.
