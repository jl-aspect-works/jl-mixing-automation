#!/usr/bin/env python3
"""Classify a change conservatively and validate changed Markdown files."""

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def main():
    base, head = sys.argv[1:]
    full_ci = True
    try:
        git("cat-file", "-e", f"{base}^{{commit}}")
        git("cat-file", "-e", f"{head}^{{commit}}")
    except subprocess.CalledProcessError:
        # A new branch or unavailable comparison base gets the full matrix.
        print("Comparison base unavailable; full CI required")
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("full_ci=true\n")
        return 0

    try:
        changed = [name.decode() for name in git(
            "diff", "--name-only", "--no-renames", "-z", base, head
        ).split(b"\0") if name]
        # Also catches whitespace errors in non-documentation changes.
        subprocess.run(["git", "diff", "--check", base, head], check=True)
        docs = [name for name in changed if name == "README.md" or
                (name.startswith("docs/") and name.endswith(".md"))]
        full_ci = not changed or len(docs) != len(changed)

        for name in docs:
            path = Path(name)
            if not path.is_file():
                continue  # Deleted documentation has no links to validate.
            content = path.read_text(encoding="utf-8")
            for match in re.finditer(r"\]\(([^)\n]+)\)", content):
                destination = match.group(1).split(" ", 1)[0].strip("<>")
                parsed = urlsplit(destination)
                if parsed.scheme or parsed.netloc or destination.startswith(("/", "#")):
                    continue
                target = unquote(parsed.path)
                if target and not (path.parent / target).exists():
                    raise ValueError(f"{name}: missing local link target {target}")
    except (subprocess.CalledProcessError, UnicodeError, ValueError) as error:
        # A validation error fails the required check; an unavailable diff
        # should never classify the change as documentation-only.
        print(f"Change-scope validation failed: {error}", file=sys.stderr)
        return 1

    print("Full CI required" if full_ci else "Documentation-only checks passed")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"full_ci={str(full_ci).lower()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
