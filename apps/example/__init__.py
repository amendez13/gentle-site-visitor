"""Wikipedia asteroid reference app registration."""

from __future__ import annotations

from apps.example.visit import build_plan
from gsv.apps import register_app

register_app("example", build_plan)

__all__ = ["build_plan"]
