"""Application registry used by the CLI to resolve site visit plans."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gsv.config import SiteConfig
    from gsv.visit import VisitContext, VisitPlan

PlanFactory = Callable[["VisitContext"], "VisitPlan"]

_REGISTRY: dict[str, PlanFactory] = {}


class AppRegistryError(LookupError):
    """Raised when a configured site cannot resolve a visit-plan factory."""


def register_app(name: str, factory: PlanFactory) -> None:
    """Register a site name to a visit-plan factory."""
    if not name:
        raise ValueError("app name is required")
    _REGISTRY[name] = factory


def get_app(name: str) -> PlanFactory:
    """Return the registered visit-plan factory for a site name."""
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise AppRegistryError(f"No app registered for site '{name}'.") from exc


def autoload(site: "SiteConfig") -> None:
    """Import a configured app module, falling back to ``apps.<site>``."""
    module_name = site.app_module or f"apps.{site.name}"
    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name or (exc.name is not None and module_name.startswith(f"{exc.name}.")):
            return
        raise


def clear_app_registry() -> None:
    """Clear registered apps for tests."""
    _REGISTRY.clear()


__all__ = [
    "AppRegistryError",
    "PlanFactory",
    "autoload",
    "clear_app_registry",
    "get_app",
    "register_app",
]
