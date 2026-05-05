"""Action steps for visit plans."""

from __future__ import annotations

from dataclasses import dataclass

from gsv.browser.primitives import click_with_position_jitter, human_type, run_humanized_page_dwell, scroll_page
from gsv.visit.context import VisitContext
from gsv.visit.plan import StepResult


@dataclass
class Click:
    """Click a selector, optionally using position jitter."""

    selector: str
    name: str = "click"
    content_marker: str | None = None
    jitter: bool = True
    wait_for: str | None = None

    async def execute(self, ctx: VisitContext) -> StepResult:
        """Click the configured selector."""
        if self.jitter:
            clicked = await click_with_position_jitter(ctx.page, self.selector, rng=ctx.rng)
        else:
            await ctx.page.click(self.selector)
            clicked = True
        if self.wait_for is not None:
            await ctx.page.wait_for_selector(self.wait_for)
        return StepResult(name=self.name, outcome="ok" if clicked else "fail")


@dataclass
class Type:
    """Type a value into a selector."""

    selector: str
    value: str
    name: str = "type"
    content_marker: str | None = None
    secret: bool = False

    async def execute(self, ctx: VisitContext) -> StepResult:
        """Type the configured value."""
        await human_type(ctx.page, self.selector, self.value, rng=ctx.rng)
        return StepResult(name=self.name, outcome="ok")


@dataclass
class Scroll:
    """Scroll the current page."""

    times: int = 1
    name: str = "scroll"
    content_marker: str | None = None

    async def execute(self, ctx: VisitContext) -> StepResult:
        """Scroll the page."""
        await scroll_page(ctx.page, times=self.times, rng=ctx.rng)
        return StepResult(name=self.name, outcome="ok")


@dataclass
class Dwell:
    """Run a humanized read/dwell sequence."""

    name: str = "dwell"
    content_marker: str | None = None
    min_seconds: float = 7.0
    max_seconds: float = 10.0

    async def execute(self, ctx: VisitContext) -> StepResult:
        """Dwell on the page and return elapsed seconds."""
        elapsed = await run_humanized_page_dwell(
            ctx.page,
            min_seconds=self.min_seconds,
            max_seconds=self.max_seconds,
            rng=ctx.rng,
        )
        return StepResult(name=self.name, outcome="ok", extracted=elapsed)
