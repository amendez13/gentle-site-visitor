"""Documented worker exit codes."""

from __future__ import annotations

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_AUTH_FAILURE = 10
EXIT_CONFIG_ERROR = 20

__all__ = [
    "EXIT_AUTH_FAILURE",
    "EXIT_CONFIG_ERROR",
    "EXIT_OK",
    "EXIT_RUNTIME_ERROR",
]
