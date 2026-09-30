#!/usr/bin/env python3
"""Fail closed unless GitHub confirms both the release tag and release are absent."""

import re
import subprocess
import sys


class ReleaseGuardError(RuntimeError):
    """Publication cannot safely proceed."""


def github_api(endpoint):
    try:
        return subprocess.run(
            ["gh", "api", "--include", endpoint],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReleaseGuardError(f"Unable to query GitHub: {type(error).__name__}") from error


def require_absent(endpoint, tag, kind):
    result = github_api(endpoint)
    if result.returncode == 0:
        raise ReleaseGuardError(
            f"{kind} {tag} already exists. Releases are immutable; use a new version/tag."
        )
    # gh returns nonzero for HTTP errors. Only a confirmed 404 means absence;
    # authentication, rate limits, outages, and malformed responses must stop publication.
    status_line = result.stdout.splitlines()[0] if result.stdout else ""
    if result.returncode != 1 or not re.fullmatch(r"HTTP/[0-9.]+ 404(?: .*)?", status_line):
        raise ReleaseGuardError(f"Cannot confirm absence of {kind.lower()} {tag}; publication stopped.")


def check_release_available(repository, tag):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ReleaseGuardError("Expected repository in owner/name form.")
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?", tag):
        raise ReleaseGuardError("Expected a version tag such as v2.3.4 or v2.3.4-rc.1.")
    # GitHub also uses 404 for inaccessible repositories. Verify repository access
    # first so those errors cannot be mistaken for an unused release version.
    if github_api(f"repos/{repository}").returncode != 0:
        raise ReleaseGuardError("Cannot verify repository access; publication stopped.")
    require_absent(f"repos/{repository}/git/ref/tags/{tag}", tag, "Tag")
    require_absent(f"repos/{repository}/releases/tags/{tag}", tag, "Release")


def main():
    if len(sys.argv) != 3:
        print("Usage: check-release-available.py OWNER/REPO TAG", file=sys.stderr)
        return 1
    try:
        check_release_available(sys.argv[1], sys.argv[2])
    except ReleaseGuardError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Confirmed unused release version: {sys.argv[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
