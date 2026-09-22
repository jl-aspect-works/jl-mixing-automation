# Managed Delivery API

Automation API 1.0 exposes read/reconciliation and generated-package management operations for Studio Delivery workflows.

## Capabilities

- `delivery.status`
- `delivery.package.delete`
- `delivery.package.rebuild`

`delivery.package.rebuild` uses the existing `delivery create --overwrite --zip` operation. There is no separate rebuild command.

## Delivery status

```text
jl-mixing delivery status --json --project PATH
```

The response operation is `delivery.status`.

The status payload reports:

- current, approved, delivered, and delivery-source revision numbers;
- manifest-managed deliverables and their SHA-256 reconciliation status;
- missing, mismatched, unsafe, unavailable, and untracked delivery artifacts;
- Delivery Notes presence and filesystem metadata;
- generated JL Mixing ZIP packages and whether each package matches the current delivery-folder snapshot;
- the newest current package when one exists.

Delivery Notes are intentionally part of ZIP currency checks. Editing `Delivery_Notes.md` after a ZIP was built makes that ZIP stale until it is rebuilt.

`state` describes authoritative delivery-manifest/deliverable readiness:

- `not_created`: there is no readable delivery manifest;
- `ready`: manifest-managed delivery files reconcile successfully;
- `needs_attention`: delivery state contains a missing, mismatched, unsafe, untracked, or source-revision problem.

`package_state` is reported separately as `none`, `current`, `stale`, or `attention`.

## Delete generated package

```text
jl-mixing delivery delete-package --json --project PATH --zip-name NAME
```

The response operation is `delivery.delete-package`.

Deletion is intentionally restricted to regular, non-symlink files whose filename matches the JL Mixing generated package convention for the current project:

```text
<project-id>-rev-NN-YYYYMMDDhhmmss.zip
```

Manifest-managed deliverables, Delivery Notes, arbitrary ZIP files, paths containing directory components, directories, and symbolic links are never deleted by this operation.

After successful deletion, the response includes a freshly reconciled `delivery.status`-equivalent object under `data.delivery`.

## Rebuild generated package

A generated ZIP is rebuilt through the existing authoritative delivery workflow:

```text
jl-mixing delivery create --json --project PATH --overwrite --zip
```

This preserves the existing manifest/hash semantics, same-path-set overwrite requirement, Delivery Notes preservation, staged replacement, and rollback behavior.

Use `--clean --zip` instead only when the delivery path set itself intentionally changes. `--clean` resets Delivery Notes according to the existing `delivery.create` contract.

## Ownership and safety

Studio may use these operations to inspect delivery state and manage generated ZIPs. Studio must not directly rename or delete manifest-managed deliverables. Automation remains authoritative for delivery creation, replacement, hashing, manifest state, and package construction.
