# JL Mixing Automation Release Checklist

`VERSION` is the single release-version source of truth. Tests and release scripts must validate `VERSION` dynamically; they must not encode the current RC or stable release number.

## Prepare the release

- [ ] Confirm all intended release changes are merged to `main` and no release-blocking PR remains open.
- [ ] Update `VERSION` to the intended SemVer value (for example `2.1.0-rc.3` or `2.1.0`).
- [ ] Do not change tests or application code solely to advance the release number.
- [ ] Update release notes only when release content or installation guidance actually changed; do not edit them solely to change an RC number.
- [ ] Before a stable release, perform a final documentation-only pass: remove RC/prerelease wording from the release notes, describe completed qualification in past tense, and verify installation/version examples match the stable release.
- [ ] Run `make release-check`.
- [ ] Open the release-preparation PR.
- [ ] Confirm ShellCheck and the complete Tests workflow are green before merge.
- [ ] Merge the release-preparation PR to `main`.

## Build and publish

- [ ] From GitHub Actions, run the **Release** workflow on `main`. Do not create the release tag manually.
- [ ] The workflow must read `VERSION`, build the exact dispatched `main` commit, and create `v${VERSION}` only after all platform builds succeed.
- [ ] Monitor the workflow through completion. If a job fails, inspect all failed jobs before changing code and rerun only after the complete failure set is understood.
- [ ] Confirm Windows package succeeds.
- [ ] Confirm macOS Intel package succeeds.
- [ ] Confirm macOS Apple Silicon package succeeds.
- [ ] Confirm Linux package succeeds.
- [ ] Confirm all archive checksums and inventories are present.
- [ ] Confirm the GitHub release is published and is marked prerelease when `VERSION` contains a prerelease suffix.

## Coordinated acceptance

- [ ] Install the published Automation package on Windows and verify the command/runtime surface.
- [ ] Install the appropriate Automation package on macOS and verify the command/runtime surface.
- [ ] Perform coordinated acceptance with the intended JL Mixing Studio candidate.
- [ ] Record release-blocking findings as issues/PRs and do not advance to the next RC or stable release until resolved or explicitly deferred.
