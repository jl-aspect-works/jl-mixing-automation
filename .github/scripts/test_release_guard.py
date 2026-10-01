#!/usr/bin/env python3
"""Release-availability behavior and workflow publication invariants."""

import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "release_guard", ROOT / ".github/scripts/check-release-available.py"
)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def response(code=0, status="200 OK"):
    return subprocess.CompletedProcess([], code, f"HTTP/2.0 {status}\n\n{{}}", "")


class ReleaseGuardTests(unittest.TestCase):
    def check(self, responses, tag="v2.3.4"):
        with patch.object(guard.subprocess, "run", side_effect=responses) as run:
            guard.check_release_available("owner/repo", tag)
        return run

    def test_unused_stable_and_rc_versions_pass(self):
        for tag in ("v2.3.4", "v2.3.4-rc.1"):
            with self.subTest(tag=tag):
                run = self.check([response(), response(1, "404 Not Found"), response(1, "404 Not Found")], tag)
                self.assertEqual([call.args[0] for call in run.call_args_list], [
                    ["gh", "api", "--include", "repos/owner/repo"],
                    ["gh", "api", "--include", f"repos/owner/repo/git/ref/tags/{tag}"],
                    ["gh", "api", "--include", f"repos/owner/repo/releases/tags/{tag}"],
                ])

    def test_existing_tag_fails_even_when_it_points_to_dispatch_commit(self):
        with self.assertRaisesRegex(guard.ReleaseGuardError, "Tag .*already exists.*new version/tag"):
            self.check([response(), response()])

    def test_existing_release_without_tag_fails(self):
        with self.assertRaisesRegex(guard.ReleaseGuardError, "Release .*already exists"):
            self.check([response(), response(1, "404 Not Found"), response()])

    def test_repository_access_failure_is_never_absence(self):
        for status in ("401 Unauthorized", "403 Forbidden", "404 Not Found", "500 Internal Server Error"):
            with self.subTest(status=status), self.assertRaisesRegex(guard.ReleaseGuardError, "repository access"):
                self.check([response(1, status)])

    def test_lookup_errors_fail_closed_for_both_resources(self):
        for resource in ("tag", "release"):
            for status in ("401 Unauthorized", "403 Forbidden", "429 Too Many Requests", "500 Internal Server Error", ""):
                results = [response()]
                if resource == "release":
                    results.append(response(1, "404 Not Found"))
                results.append(response(1, status))
                with self.subTest(resource=resource, status=status), self.assertRaisesRegex(guard.ReleaseGuardError, "Cannot confirm absence"):
                    self.check(results)

    def test_untrusted_or_inconsistent_not_found_responses_fail(self):
        for result in (
            subprocess.CompletedProcess([], 1, '{"message":"Not Found"}', ""),
            subprocess.CompletedProcess([], 1, "", "HTTP/2.0 404 Not Found"),
            response(2, "404 Not Found"),
            response(0, "404 Not Found"),
        ):
            with self.subTest(result=result), self.assertRaises(guard.ReleaseGuardError):
                self.check([response(), result])

    def test_missing_cli_and_timeout_fail_closed(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("gh", 60)):
            with self.subTest(error=error), self.assertRaisesRegex(guard.ReleaseGuardError, "Unable to query GitHub"):
                self.check([error])

    def test_invalid_arguments_do_not_query_github(self):
        for repository, tag in (("owner", "v2.3.4"), ("owner/repo", "refs/tags/v2.3.4"), ("owner/repo", "v2.3.4?bad")):
            with patch.object(guard.subprocess, "run") as run:
                with self.assertRaises(guard.ReleaseGuardError):
                    guard.check_release_available(repository, tag)
                run.assert_not_called()

    def test_workflow_guards_before_build_and_before_tag_creation(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        validate, remainder = workflow.split("  build:", 1)
        publish = remainder.split("  publish:", 1)[1]
        invocation = 'python3 .github/scripts/check-release-available.py "$GITHUB_REPOSITORY" "$RELEASE_TAG"'
        self.assertIn(invocation, validate)
        self.assertIn('RELEASE_TAG: ${{ steps.version.outputs.tag }}', validate)
        self.assertLess(publish.index(invocation), publish.index('git tag -a'))
        self.assertEqual(workflow.count(invocation), 2)
        self.assertEqual(workflow.count('GH_TOKEN: ${{ github.token }}'), 3)
        self.assertIn("group: release-publication", workflow)
        self.assertNotIn("--clobber", workflow)
        self.assertNotIn("gh release upload", workflow)
        self.assertNotIn("gh release view", workflow)
        self.assertNotIn("git rev-parse", publish)
        self.assertIn('git push origin "refs/tags/$RELEASE_TAG"', publish)
        self.assertIn('gh release create "$RELEASE_TAG"', publish)
        for preserved in ("--verify-tag", "--prerelease", "--notes-file", "subject-path: release-assets/*"):
            self.assertIn(preserved, publish)
        ci = ROOT / ".github/workflows" / ("ci.yml" if (ROOT / "package.json").exists() else "tests.yml")
        self.assertIn("python3 .github/scripts/test_release_guard.py", ci.read_text())


if __name__ == "__main__":
    unittest.main()
