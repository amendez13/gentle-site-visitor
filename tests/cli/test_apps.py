"""Tests for the app registry."""

from __future__ import annotations

import pytest

from gsv.apps import AppRegistryError, autoload, clear_app_registry, get_app, register_app
from gsv.config import SiteConfig
from tests.cli.stub_app import build_plan


def test_registry_get_app_errors_when_missing() -> None:
    """Missing apps produce a clear registry error."""
    clear_app_registry()

    with pytest.raises(AppRegistryError, match="missing"):
        get_app("missing")


def test_registry_registers_and_autoload_ignores_absent_default_module() -> None:
    """Manual registration works; absent default app modules are optional in S6 tests."""
    clear_app_registry()
    autoload(SiteConfig(name="not_installed"))
    register_app("example", build_plan)

    assert get_app("example") is build_plan


def test_register_app_requires_name() -> None:
    """Empty registry names are rejected."""
    with pytest.raises(ValueError, match="app name"):
        register_app("", build_plan)
