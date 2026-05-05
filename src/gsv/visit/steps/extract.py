"""Extraction steps for visit plans."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from gsv.visit.context import VisitContext
from gsv.visit.plan import StepResult


@dataclass(frozen=True)
class EmptyResult:
    """Sentinel namespace for extractor outcomes that need framework handling."""

    HYDRATION_NEEDED = "hydration_needed"


@dataclass
class Extract:
    """Run an app-owned extractor and store the result in the context."""

    extractor: Callable[[Any], Awaitable[Any]]
    output_key: str
    name: str = "extract"
    content_marker: str | None = None

    async def execute(self, ctx: VisitContext) -> StepResult:
        """Run the extractor against the current page."""
        value = await self.extractor(ctx.page)
        ctx.extracted[self.output_key] = value
        return StepResult(name=self.name, outcome="ok", extracted=value)
