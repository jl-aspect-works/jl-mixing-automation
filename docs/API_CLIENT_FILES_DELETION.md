# Original Delivery deletion API

API 1.0 advertises `client.files.delete.plan` and `client.files.delete.execute` when installed:

```bash
jl-mixing client-files delete-plan --json --project PROJECT --relative-path 01_Client_Files/Original_Delivery/FILE
jl-mixing client-files delete-execute --json --project PROJECT --relative-path 01_Client_Files/Original_Delivery/FILE --fingerprint PLAN_FINGERPRINT --confirm-name EXACT_NAME
```

The plan returns `data.summary`: project-relative path, item name, recursive file and folder counts, bytes, snapshot fingerprint, and `working_copies_retained`. Existing Working Audio copies stay in place. Execution checks the fingerprint and exact name again, stages the target away from Original Delivery, removes matching entries from the Automation-authored Audio Prep lineage record, then permanently deletes the staged item. It never follows a symlink or deletes a managed root. A folder containing symlinks or special entries is blocked as a whole.

A failed lineage write restores the staged target where possible. A cleanup failure reports `PARTIAL_CLEANUP` with `remaining_path`; do not retry automatically. There is no trash or undo. Other applications must stop writing to the target during plan and execution; the fingerprint is not a cross-process lock. Older Automation releases do not advertise this capability, and Studio should not offer this action against them.
