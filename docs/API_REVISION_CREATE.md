# Automation API `revision.create`

The Automation API 1.0 revision-creation operation is invoked through:

```bash
jl-mixing revision create --json --project PROJECT_PATH [options]
```

The operation executes the existing revision-creation implementation in-process. It preserves the same revision numbering, source validation/import behavior, manifest update rules, project-state validation, and transactional directory+manifest commit used by `new-revision`.

Supported inputs mirror the non-interactive `new-revision` inputs: `--project`, `--description`, `--source`, and `--dry-run`. Machine-facing calls do not accept `--cd` or `--no-cd`.

A successful creation returns `status: success` with explicit project, manifest, revision, revision-notes, and workspace paths. A valid dry run returns `status: planned`, reports the next revision number and affected paths, and does not mutate project state. Failures preserve the Automation exit-code contract and return stable machine-readable error codes in the API 1.0 response envelope.

`system-info --json` advertises `revision.create` only while the implementation, schema, examples, parity coverage, and release artifacts are present.
