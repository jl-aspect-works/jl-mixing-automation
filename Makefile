# Use Bash consistently for recipes on macOS and Linux.
SHELL := /bin/bash

# These targets are actions, not files.
.PHONY: help test strict-test schema-test check install uninstall install-test release release-check

# Display the current command, development, installation, and release surfaces.
help:
	@echo "JL Mixing Automation v$$(cat VERSION)"
	@echo
	@echo "Testing:"
	@echo "  make test          Run dependency-tolerant artifact, unit, integration, and schema tests"
	@echo "  make strict-test   Require all runtime dependencies and installation/package tests"
	@echo "  make schema-test   Run only strict JSON Schema validation"
	@echo "  make check         Check dependencies and run ShellCheck when installed"
	@echo "  make install-test  Run installation and release-package tests"
	@echo
	@echo "Installation and release:"
	@echo "  make install       Install under ~/.local (override with PREFIX=path)"
	@echo "  make uninstall     Uninstall from ~/.local (override with PREFIX=path)"
	@echo "  make release       Build the end-user tarball under dist/"
	@echo "  make release-check Run all release gates and verify a clean archive"

# Run all checks that can execute with the currently available dependencies.
test:
	@tests/run-tests.sh

# Require all runtime/development dependencies and execute the complete suite.
strict-test:
	@PYTHON="$${JL_MIXING_PYTHON:-}"; \
	if [ -z "$$PYTHON" ] && [ -x .venv/bin/python ]; then PYTHON=.venv/bin/python; fi; \
	if [ -z "$$PYTHON" ]; then PYTHON="$$(command -v python3 || true)"; fi; \
	[ -n "$$PYTHON" ] || { echo "Missing Python 3" >&2; exit 1; }; \
	command -v jq >/dev/null 2>&1 || { echo "Missing required command: jq" >&2; exit 1; }; \
	"$$PYTHON" -c 'import jsonschema' 2>/dev/null || { echo "Missing jsonschema. Run: python3 -m venv .venv && .venv/bin/pip install -r packaging/requirements.txt" >&2; exit 1; }; \
	JL_MIXING_PYTHON="$$PYTHON" JL_TEST_STRICT=1 tests/run-tests.sh

# Run semantic Draft 2020-12 validation only.
schema-test:
	@PYTHON="$${JL_MIXING_PYTHON:-}"; \
	if [ -z "$$PYTHON" ] && [ -x .venv/bin/python ]; then PYTHON=.venv/bin/python; fi; \
	if [ -z "$$PYTHON" ]; then PYTHON="$$(command -v python3 || true)"; fi; \
	[ -n "$$PYTHON" ] || { echo "Missing Python 3" >&2; exit 1; }; \
	"$$PYTHON" -c 'import jsonschema' 2>/dev/null || { echo "Missing jsonschema. Run: python3 -m venv .venv && .venv/bin/pip install -r packaging/requirements.txt" >&2; exit 1; }; \
	"$$PYTHON" tools/validate-json.py --strict

# Check dependencies and static shell analysis.
check:
	@tools/check-dependencies
	@tools/shellcheck-all

# Install or uninstall under PREFIX without changing project workspaces.
install:
	@./install.sh --prefix "$${PREFIX:-$$HOME/.local}"

uninstall:
	@./uninstall.sh --prefix "$${PREFIX:-$$HOME/.local}"

# Run only the current installation and package lifecycle tests.
install-test:
	@JL_TEST_STRICT=1 tests/installation/test-installation.sh
	@JL_TEST_STRICT=1 tests/installation/test-release-package.sh

# Build a versioned end-user release tarball.
release:
	@tools/build-release

# Run tests, ShellCheck, build, extraction, installation, upgrade, and uninstall checks.
release-check:
	@tools/release-check
