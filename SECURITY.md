# Security Policy

## Supported versions

JL Mixing Automation maintains the current `2.3.x` release line. Security fixes are made on the current development line and, when appropriate, released as maintenance updates.

Prerelease builds such as release candidates are provided for qualification and may change before stable release. Older release lines are not guaranteed to receive security fixes.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability involving arbitrary command execution, path traversal, destructive filesystem behavior, archive or package handling, dependency compromise, credential exposure, or exposure of private project data.

Use GitHub's private vulnerability reporting feature when it is enabled for this repository. If private reporting is unavailable, contact the repository owner privately before disclosing details publicly.

Please include:

- A concise description of the issue.
- The affected version or commit.
- Reproduction steps or a proof of concept when practical.
- Expected impact.
- Any suggested mitigation.

## Security principles

JL Mixing Automation is designed to:

- Validate filesystem paths and managed workspace boundaries before destructive operations.
- Restrict subprocess execution to intended, validated operations.
- Avoid executing untrusted project content as code.
- Preserve explicit handling for overwrite and destructive actions.
- Keep packaged runtime and dependency changes reviewable through version-controlled build inputs.

Security reports are evaluated based on reproducibility, impact, and the affected supported version. No fixed response-time or disclosure SLA is currently promised.
