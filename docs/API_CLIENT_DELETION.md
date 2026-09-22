# Client deletion API

Automation API 1.0 advertises `client.delete.plan` and `client.delete.execute` when the corresponding commands are installed.

```text
jl-mixing client delete-plan --json --workspace WORKSPACE --client-id CLIENT_ID
jl-mixing client delete-execute --json --workspace WORKSPACE --client-id CLIENT_ID --fingerprint PLAN_FINGERPRINT --confirm-name EXACT_CLIENT_NAME
```

The caller supplies the configured workspace and stable Client ID, never a client filesystem path. Both operations validate the Studio and client documents, path containment, unique identity, and the complete client directory. Symlinks, junctions, special entries, and nested mounts are rejected.

Deletion is allowed only when `Projects` contains no project directory. An unrecognized or malformed directory under `Projects` still blocks deletion so Automation never treats uncertain project content as disposable. Ordinary files directly under `Projects`, and other non-project content within the client directory, are summarized and permanently deleted with the client.

The plan returns the exact Client Name, Client ID, canonical path, document ID, authoritative zero project count, file count, total bytes, and a fingerprint of the inspected state. Studio must show that summary before execution. Execution requires the fingerprint and exact, case-sensitive Client Name, re-reads the authoritative state, and rejects new projects or any other changed content.

This is permanent deletion: **there is no trash or recovery facility**. Do not use this command as a keyboard dialog default action.

The client is moved to a hidden same-filesystem staging name before recursive removal. A filesystem failure after that move returns `PARTIAL_CLEANUP`, `deleted: false`, and `remaining_path`; Studio must not display success, retry automatically, or delete the residual path itself. An interruption can likewise leave `.deleting-client-*` content under `Clients` for explicit operator review. Other concurrent writers must be stopped by the caller; a plan fingerprint is not a cross-process lock.
