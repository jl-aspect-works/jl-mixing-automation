# JL Mixing Automation v1.3.0 Release Notes

JL Mixing Automation v1.3 is a delivery-package naming release built on v1.2.
It preserves the v1.1 workspace schemas and existing project lifecycle.

## Highlights

- Delivery ZIPs use
  `<project-id>-rev-<NN>-<YYYYMMDDHHMMSS>.zip`.
- The revision is the approved revision being delivered and is zero-padded.
- The ZIP timestamp uses the computer's local timezone. Schema-governed manifest
  timestamps remain in UTC.
- Earlier generated ZIPs may remain in `05_Final_Delivery`, but they are never
  nested inside a later archive.

## Compatibility

v1.3 continues using the exact v1.1.0 JSON schema identities and supports valid
v1.1 and v1.2 workspaces. JL Mixing Studio 1.0 requires Automation v1.3.0 for
guided delivery creation.
