# Automation API: `revision.approve`

`revision.approve` exposes the existing revision approval workflow through Automation API 1.0.

```bash
jl-mixing revision approve --json --project /path/to/project
```

The machine-facing route uses the same authoritative implementation as `approve-mix`; it does not launch the human command as a subprocess.

## Request options

JSON mode requires exactly one explicit `--project PATH` and accepts the existing approval options:

- `--revision NUMBER` — revision to approve; defaults to the current revision
- `--approved-by NAME` — defaults to `Client`
- `--date TIMESTAMP` — timezone-qualified ISO-8601 timestamp; defaults to execution time
- `--dry-run` — preview the manifest-only mutation

## Results

Successful approval returns the project and manifest paths, workspace path, approved revision number/path, approver, and approval timestamp.

Dry-run returns `status: planned`, does not modify the manifest, and reports the manifest in `would_update`. When no explicit `--date` is supplied, `approved_at` is null in the plan because the timestamp is chosen only at execution.

Approval changes only the project manifest. Revision files, `current_revision`, and `delivered_revision` retain the existing `approve-mix` behavior.

Already-approved and invalid revision states return `status: blocked` with exit code 5 and stable machine codes such as `REVISION_ALREADY_APPROVED` or `REVISION_NOT_FOUND`. Invalid timestamps use `INVALID_APPROVAL_TIMESTAMP`. Request/context failures retain the API 1.0 exit-code mapping.

## Contract artifacts

The response schema is:

`api/schemas/v1.0/operations/revision-approve.schema.json`

Golden success, planned, and blocked examples ship under `api/examples/v1.0/`.
