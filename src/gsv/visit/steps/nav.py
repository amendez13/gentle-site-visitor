"""Navigation steps for visit plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from gsv.visit.context import VisitContext
from gsv.visit.plan import StepResult

WaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]


@dataclass
class Navigate:
    """Navigate the page to a URL."""

    url: str
    name: str = "navigate"
    content_marker: str | None = None
    wait_until: WaitUntil = "domcontentloaded"

    async def execute(self, ctx: VisitContext) -> StepResult:
        """Navigate to the configured URL."""
        await ctx.page.goto(self.url, wait_until=self.wait_until)
        return StepResult(name=self.name, outcome="ok")


@dataclass
class WaitFor:
    """Wait for a selector to appear."""

    selector: str
    name: str = "wait_for"
    content_marker: str | None = None
    timeout_ms: int = 10000
    retries: int = 0

    async def execute(self, ctx: VisitContext) -> StepResult:
        """Wait for the selector, retrying when configured."""
        attempts = 0
        while True:
            try:
                await ctx.page.wait_for_selector(self.selector, timeout=self.timeout_ms)
                return StepResult(name=self.name, outcome="ok")
            except Exception:
                if attempts >= self.retries:
                    raise
                attempts += 1
                ctx.increment("hydration_retries")
