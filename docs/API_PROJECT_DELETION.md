# Project deletion API

Automation API 1.0 advertises `project.delete.plan` and `project.delete.execute` when the corresponding commands are installed.

```text
jl-mixing project delete-plan --json --workspace WORKSPACE --client-id CLIENT_ID --project-id PROJECT_ID
jl-mixing project delete-execute --json --workspace WORKSPACE --client-id CLIENT_ID --project-id PROJECT_ID --fingerprint PLAN_FINGERPRINT --confirm-name EXACT_PROJECT_NAME
```

The caller supplies the configured workspace, not a project filesystem path. Both operations resolve the target by stable IDs, validate the Studio, client, and project documents and ownership, reject ambiguous IDs, symlinks, junctions, special entries, and nested mounts, and inspect the entire project directory. The plan returns the exact client and project identity, project path, file count, total file bytes, and a fingerprint of the inspected state. The deletion summary must be shown before execution.

Execution requires both the fingerprint from that summary and the exact, case-sensitive Project Name typed by the user. It re-reads the authoritative state and rejects a stale summary before mutation. This is permanent deletion: **there is no trash or recovery facility**. Everything inside the project directory is in scope, including user audio, DAW projects, revisions, deliveries, reports, and metadata. Do not use this command as a keyboard dialog default action.

External Revision and Delivered Listening copies are deliberately **retained**. They are not part of the deleted project directory and must be disclosed as remaining copies in the Studio confirmation and result. Automation does not know Studio's configured external Listening destinations and does not claim to enumerate or delete them.

The project is moved out of the active `Projects` directory before recursive deletion. A filesystem failure after that move returns `PARTIAL_CLEANUP`, `deleted: false`, and `remaining_path`; Studio must not display success or attempt to delete the residual path itself. An interruption can likewise leave `.deleting-*` content under the client directory that requires explicit operator review. No unrelated client/project directory is intentionally changed. Other concurrent writers must be stopped by the caller; a plan fingerprint is not a cross-process lock.
