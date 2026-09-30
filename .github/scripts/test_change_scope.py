#!/usr/bin/env python3
"""Regression tests for the conservative CI change-scope classifier."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check-change-scope.py").resolve()


def run(*args, cwd, check=True, env=None):
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


class ChangeScopeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tempdir.name)
        run("git", "init", "-b", "main", cwd=self.repo)
        run("git", "config", "user.email", "ci@example.invalid", cwd=self.repo)
        run("git", "config", "user.name", "CI Test", cwd=self.repo)
        self.write("README.md", "# Test\n")
        self.commit("initial")
        self.base = self.rev()

    def tearDown(self):
        self.tempdir.cleanup()

    def write(self, relative, content):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit(self, message):
        run("git", "add", "-A", cwd=self.repo)
        run("git", "commit", "-m", message, cwd=self.repo)

    def rev(self):
        return run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip()

    def classify(self, base=None, head=None):
        output = self.repo / "github-output.txt"
        output.write_text("", encoding="utf-8")
        env = os.environ.copy()
        env["GITHUB_OUTPUT"] = str(output)
        result = run(
            sys.executable,
            str(SCRIPT),
            base or self.base,
            head or self.rev(),
            cwd=self.repo,
            check=False,
            env=env,
        )
        values = {}
        for line in output.read_text(encoding="utf-8").splitlines():
            key, value = line.split("=", 1)
            values[key] = value
        return result, values

    def commit_change(self, relative, content="changed\n"):
        self.write(relative, content)
        self.commit(f"change {relative}")

    def test_readme_only_is_documentation_only(self):
        self.commit_change("README.md", "# Updated\n")
        result, values = self.classify()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(values.get("full_ci"), "false")

    def test_docs_markdown_only_is_documentation_only(self):
        self.commit_change("docs/guide.md", "# Guide\n")
        result, values = self.classify()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(values.get("full_ci"), "false")

    def test_deleted_documentation_is_documentation_only(self):
        self.write("docs/old.md", "# Old\n")
        self.commit("add old doc")
        base = self.rev()
        (self.repo / "docs/old.md").unlink()
        self.commit("delete old doc")
        result, values = self.classify(base=base)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(values.get("full_ci"), "false")

    def test_code_plus_docs_requires_full_ci(self):
        self.write("docs/guide.md", "# Guide\n")
        self.write("src/app.rs", "fn main() {}\n")
        self.commit("mixed change")
        result, values = self.classify()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(values.get("full_ci"), "true")

    def test_workflow_change_requires_full_ci(self):
        self.commit_change(".github/workflows/ci.yml", "name: CI\n")
        result, values = self.classify()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(values.get("full_ci"), "true")

    def test_classifier_script_change_requires_full_ci(self):
        self.commit_change(".github/scripts/check-change-scope.py", "# changed\n")
        result, values = self.classify()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(values.get("full_ci"), "true")

    def test_dependency_build_package_and_release_paths_require_full_ci(self):
        for path in ("package.json", "Cargo.toml", "packaging/requirements.txt", "VERSION"):
            with self.subTest(path=path):
                with tempfile.TemporaryDirectory() as td:
                    # Use a fresh repository per subtest so each diff is isolated.
                    repo = Path(td)
                    run("git", "init", "-b", "main", cwd=repo)
                    run("git", "config", "user.email", "ci@example.invalid", cwd=repo)
                    run("git", "config", "user.name", "CI Test", cwd=repo)
                    (repo / "README.md").write_text("# Test\n", encoding="utf-8")
                    run("git", "add", "-A", cwd=repo)
                    run("git", "commit", "-m", "initial", cwd=repo)
                    base = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
                    target = repo / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("changed\n", encoding="utf-8")
                    run("git", "add", "-A", cwd=repo)
                    run("git", "commit", "-m", "change", cwd=repo)
                    head = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
                    output = repo / "github-output.txt"
                    output.write_text("", encoding="utf-8")
                    env = os.environ.copy()
                    env["GITHUB_OUTPUT"] = str(output)
                    result = run(sys.executable, str(SCRIPT), base, head, cwd=repo, check=False, env=env)
                    self.assertEqual(result.returncode, 0)
                    self.assertIn("full_ci=true", output.read_text(encoding="utf-8"))

    def test_root_security_markdown_requires_full_ci(self):
        self.commit_change("SECURITY.md", "# Security\n")
        result, values = self.classify()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(values.get("full_ci"), "true")

    def test_lookalike_doc_paths_require_full_ci(self):
        for path in ("docs-notes/guide.md", "docs/guide.txt", "DOCS/guide.md"):
            with self.subTest(path=path):
                self.commit_change(path, "text\n")
                result, values = self.classify()
                self.assertEqual(result.returncode, 0)
                self.assertEqual(values.get("full_ci"), "true")
                self.base = self.rev()

    def test_empty_diff_requires_full_ci(self):
        head = self.rev()
        result, values = self.classify(base=head, head=head)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(values.get("full_ci"), "true")

    def test_unavailable_base_fails_closed_to_full_ci(self):
        result, values = self.classify(base="0" * 40)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(values.get("full_ci"), "true")

    def test_invalid_local_markdown_link_fails_required_check(self):
        self.commit_change("docs/guide.md", "[missing](missing.md)\n")
        result, values = self.classify()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("full_ci", values)

    def test_diff_whitespace_error_fails_required_check(self):
        self.commit_change("docs/guide.md", "trailing space   \n")
        result, values = self.classify()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("full_ci", values)


if __name__ == "__main__":
    unittest.main()
