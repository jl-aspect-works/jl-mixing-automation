# Automation API `project.create`

The Automation API 1.0 project-creation operation is invoked through:

```bash
jl-mixing project create PROJECT_NAME --json [options]
```

The operation uses the same in-process transactional project-creation implementation as `new-mix`; it does not invoke the human-facing command as a subprocess.

Supported inputs mirror the non-interactive project inputs of `new-mix`, including client selection, project metadata, audio format, deliverables, source import, and `--dry-run`. Machine-facing calls do not accept `--cd` or `--no-cd`.

A successful creation returns `status: success` with explicit project, manifest, client-snapshot, initial-revision, client, and workspace paths. A valid dry run returns `status: planned` without creating project state. Failures preserve the Automation exit-code contract and return stable machine-readable error codes in the API 1.0 response envelope.

`system-info --json` advertises `project.create` only while the implementation, schemas, examples, parity tests, and packaged contract are present.
