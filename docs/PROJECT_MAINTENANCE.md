# JL Mixing Automation
## Git and Make Maintenance Guide

This guide contains the common Git and Make commands used to maintain the JL Mixing Automation project.

It assumes the repository is located at:

```text
~/Development/jlaudio/jl-mixing
```

The examples use protected `main` and `develop/v1.1` branches. v1.1 feature branches merge into `develop/v1.1`; the final release PR merges `develop/v1.1` into `main`.

---

# 1. Open the repository

```bash
cd ~/Development/jlaudio/jl-mixing
git branch --show-current
git status
```

For a compact status view:

```bash
git status --short
```

No output means the working tree is clean.

---

# 2. Update local `main`

Before starting new work:

```bash
git checkout main
git pull origin main
git status
```

Do not begin feature work directly on `main`.

---

# 3. Create a feature branch

```bash
git checkout -b feature/descriptive-feature-name
```

Examples:

```bash
git checkout -b feature/intake-audio-qc
git checkout -b feature/self-extracting-installer
git checkout -b fix/release-workflow
git checkout -b docs/install-instructions
```

Verify the branch:

```bash
git branch --show-current
```

---

# 4. Inspect changes

```bash
git status --short
git diff --stat
git diff
git diff --check
```

Inspect one file:

```bash
git diff -- README.md
```

Inspect staged changes:

```bash
git diff --cached
```

---

# 5. Activate the development environment

```bash
cd ~/Development/jlaudio/jl-mixing
source .venv/bin/activate
```

Verify Python:

```bash
which python3
python3 --version
```

Deactivate when finished:

```bash
deactivate
```

---

# 6. Common Make commands

Show available targets:

```bash
make help
```

Run normal tests:

```bash
make test
```

Run strict tests, including JSON Schema validation:

```bash
make strict-test
```

Run the complete release gate:

```bash
make release-check
```

Build the end-user release package:

```bash
make release
```

Generated packages are written to:

```text
dist/
```

Typical output:

```text
dist/jl-mixing-x.y.z-macos.tar.gz
dist/jl-mixing-x.y.z-macos.tar.gz.sha256
dist/jl-mixing-x.y.z-macos.tar.gz.inventory.txt
```

---

# 7. Run ShellCheck

```bash
tools/shellcheck-all
```

Verify ShellCheck is installed:

```bash
which shellcheck
shellcheck --version
```

Before pushing a normal branch:

```bash
tools/shellcheck-all
make test
make strict-test
```

Before a release:

```bash
tools/shellcheck-all
make test
make strict-test
make release-check
```

---

# 8. Stage and commit changes

Review before staging:

```bash
git status
git diff --stat
git diff
```

Stage all intended changes:

```bash
git add .
```

Or stage selected files:

```bash
git add README.md
git add .github/workflows/release.yml
```

Review the staged commit:

```bash
git diff --cached
```

Commit:

```bash
git commit -m "Describe the completed change"
```

Examples:

```bash
git commit -m "Add end-user installation instructions"
git commit -m "Implement intake audio validation"
git commit -m "Fix GitHub release publishing workflow"
git commit -m "Document project maintenance commands"
```

---

# 9. Push a feature branch

First push:

```bash
git push -u origin "$(git branch --show-current)"
```

Later pushes:

```bash
git push
```

Open or update the pull request in GitHub. Do not merge until required CI checks pass.

---

# 10. Update a feature branch from `main`

Commit or stash local work first.

```bash
git fetch origin
git merge origin/main
```

Then rerun:

```bash
tools/shellcheck-all
make test
make strict-test
git push
```

For this project, merging `origin/main` is usually simpler and safer than rewriting branch history with rebase.

---

# 11. After a pull request is merged

```bash
git checkout main
git pull origin main
```

Delete the local feature branch:

```bash
git branch -d feature/descriptive-feature-name
```

Delete the remote branch if needed:

```bash
git push origin --delete feature/descriptive-feature-name
```

---

# 12. Temporarily save unfinished work

```bash
git stash push -u -m "Describe unfinished work"
git stash list
git stash pop
```

Restore without removing the stash:

```bash
git stash apply
```

---

# 13. Undo local changes safely

Discard unstaged changes in one file:

```bash
git restore path/to/file
```

Discard all unstaged tracked-file changes:

```bash
git restore .
```

Unstage while preserving edits:

```bash
git restore --staged path/to/file
```

Amend the newest local commit:

```bash
git add .
git commit --amend
```

Avoid rewriting commits other people may already be using.

---

# 14. Inspect history

```bash
git log --oneline --decorate -10
git log --oneline --graph --decorate --all
git show <commit-hash>
git describe --tags --always
```

---

# 15. Prepare a patch release

Update `main` and create a release branch:

```bash
git checkout main
git pull origin main
git checkout -b release/v1.1.0
```

Update the application version:

```bash
printf '1.1.0\n' > VERSION
```

Search for unintended hard-coded version references:

```bash
grep -RIn \
  --exclude-dir=.git \
  --exclude-dir=.venv \
  --exclude='*.tar.gz' \
  '1\.0\.4' .
```

Run the release checks:

```bash
source .venv/bin/activate

tools/shellcheck-all
make test
make strict-test
make release-check
```

Commit and push:

```bash
git add .
git commit -m "Prepare JL Mixing Automation v1.1.0"
git push -u origin release/v1.1.0
```

Merge only after all PR checks pass.

---

# 16. Tag and publish a release

After the release PR is merged:

```bash
git checkout main
git pull origin main
git status --short
cat VERSION
```

Confirm the working tree is clean, then run:

```bash
source .venv/bin/activate
make release-check
```

Create and push an annotated tag:

```bash
git tag -a v1.1.0 -m "JL Mixing Automation v1.1.0"
git push origin v1.1.0
```

Verify:

```bash
git show v1.1.0 --no-patch
```

Pushing the tag triggers `.github/workflows/release.yml`.

Expected custom assets:

```text
jl-mixing-1.1.0-macos.tar.gz
jl-mixing-1.1.0-macos.tar.gz.sha256
jl-mixing-1.1.0-macos.tar.gz.inventory.txt

jl-mixing-1.1.0-linux.tar.gz
jl-mixing-1.1.0-linux.tar.gz.sha256
jl-mixing-1.1.0-linux.tar.gz.inventory.txt
```

GitHub also automatically adds:

```text
Source code (zip)
Source code (tar.gz)
```

Those are source snapshots, not the end-user installer packages.

---

# 17. Manually rerun the release workflow

In GitHub:

```text
Actions
→ Release
→ Run workflow
```

Enter an existing tag, for example:

```text
v1.1.0
```

This can recover from a publish-stage failure when the tagged source is correct.

---

# 18. Build a release locally

```bash
source .venv/bin/activate
make release-check
make release
```

Inspect generated files:

```bash
find dist -maxdepth 1 -type f -print | sort
```

Verify a checksum on macOS:

```bash
shasum -a 256 -c dist/jl-mixing-x.y.z-macos.tar.gz.sha256
```

Inspect the archive:

```bash
tar -tzf dist/jl-mixing-x.y.z-macos.tar.gz
```

---

# 19. Manual isolated installation test

Create temporary locations:

```bash
TEST_ROOT="$(mktemp -d)"
TEST_PREFIX="$TEST_ROOT/install"
TEST_STUDIO="$TEST_ROOT/Mixes"
```

Install:

```bash
./install.sh --prefix "$TEST_PREFIX"
```

Use the installed commands:

```bash
export PATH="$TEST_PREFIX/bin:$PATH"

which new-studio

new-studio \
  --root "$TEST_STUDIO" \
  --non-interactive
```

Uninstall:

```bash
./uninstall.sh --prefix "$TEST_PREFIX"
```

Confirm application removal and workspace preservation:

```bash
test ! -d "$TEST_PREFIX/share/jl-mixing" &&
    echo "[OK] Application removed"

test -d "$TEST_STUDIO" &&
    echo "[OK] Studio workspace preserved"
```

Clean up:

```bash
rm -rf "$TEST_ROOT"
```

---

# 20. Tag safety

Published tags are immutable.

If a release needs correction, create a new patch version:

```text
v1.1.0 → v1.1.1
```

Do not move or reuse an existing published tag.

```bash
git tag -l
git show v1.1.0 --no-patch
```

---

# 21. Common daily workflow

```bash
cd ~/Development/jlaudio/jl-mixing

git checkout develop/v1.1
git pull origin develop/v1.1

git checkout -b feature/example-change

# Edit files.

source .venv/bin/activate
tools/shellcheck-all
make test
make strict-test

git status
git diff --check
git add .
git diff --cached
git commit -m "Implement example change"
git push -u origin feature/example-change
```

After merge:

```bash
git checkout main
git pull origin main
git branch -d feature/example-change
```

---

# 22. Release checklist

```text
[ ] Release changes are merged into main
[ ] Local main matches origin/main
[ ] Working tree is clean
[ ] VERSION contains the intended release
[ ] ShellCheck passes
[ ] make test passes
[ ] make strict-test passes
[ ] make release-check passes
[ ] Documentation matches current behavior
[ ] Release workflow exists in the tagged commit
[ ] Annotated release tag is pushed
[ ] macOS and Linux assets appear in GitHub Releases
[ ] Checksums and inventories are attached
```
