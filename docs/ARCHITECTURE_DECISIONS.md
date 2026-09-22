# Architecture Decisions

- Application installation and studio workspaces are separate.
- The default workspace is `~/Music/Mixes/`.
- Projects live directly beneath each client's `Projects/` directory and keep a
  stable path.
- Project lifecycle is derived from `current_revision`, `approved_revision`, and
  `delivered_revision`; there is no completed-project state or command.
- `03_DAW_Project/` is an opaque DAW/user-owned boundary. JL Mixing does not
  manage DAW templates, presets, or project metadata.
- Original client delivery files are immutable.
- JSON contains machine-managed state; Markdown contains human documentation.
- Only explicitly managed Markdown sections may be rewritten automatically.
- Client profile snapshots are immutable historical records.
- Revision status is derived, not stored.
- The authoritative v1.5 workflow implementation is cross-platform Python.
  Platform-specific Bash, PowerShell, installer, and launcher code is thin glue
  and must not become a second implementation.
- Automation application versions, Automation API versions, and workspace
  metadata schema versions are independent contracts.
- Automation API remains `1.0` for v1.5 and workspace metadata remains `1.1.0`.
- Machine clients use capability discovery; they do not parse human CLI output
  or infer compatibility from the Automation product version.
- `validate-intake` is non-destructive to original delivery files and may perform
  metadata, decode-integrity, exact duplicate, format, channel, and exact
  dual-mono checks. Unavailable external tools produce skipped-check reporting.
- Delivery file eligibility is not restricted by extension.
- Delivery classification is best-effort; unmatched files are `unclassified`.
- `create-delivery --clean` explicitly authorizes removal of every item inside
  `05_Final_Delivery/` and remains rollback-capable.
- Installation, upgrades, shell configuration, and uninstall are transactional
  and preserve user workspaces.
- Windows and macOS end-user packages carry a private runtime so users do not
  need a separate Python/Bash/jq runtime installation.
- Linux/source installation remains a compatibility path and may retain external
  developer/runtime prerequisites.
