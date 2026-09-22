"""Shared JL Mixing runtime errors and stable exit-code semantics."""

from __future__ import annotations

EXIT_GENERAL = 1
EXIT_ARGUMENTS = 2
EXIT_CONFIG = 3
EXIT_CONTEXT = 4
EXIT_VALIDATION = 5
EXIT_UNSAFE = 6


class JLMixingError(RuntimeError):
    """Base exception carrying the existing CLI exit-code contract."""

    exit_code = EXIT_GENERAL


class ArgumentError(JLMixingError):
    exit_code = EXIT_ARGUMENTS


class ConfigurationError(JLMixingError):
    exit_code = EXIT_CONFIG


class ContextError(JLMixingError):
    exit_code = EXIT_CONTEXT


class ValidationError(JLMixingError):
    exit_code = EXIT_VALIDATION


class UnsafeOperationError(JLMixingError):
    exit_code = EXIT_UNSAFE
