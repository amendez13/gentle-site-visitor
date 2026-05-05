"""Control-flow steps for visit plans."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from gsv.browser.primitives import random_delay
from gsv.visit.context import VisitContext
from gsv.visit.plan import StepResult, VisitStep
from gsv.visit.steps.extract import EmptyResult


@dataclass
class Branch:
    """Choose one subtree based on an async condition."""

    condition: Callable[[VisitContext], Awaitable[bool]]
    then_steps: list[VisitStep]
    else_steps: list[VisitStep] = field(default_factory=list)
    name: str = "branch"
    content_marker: str | None = None

    async def execute(self, ctx: VisitContext) -> StepResult:
        """Run only the selected branch through a nested runner."""
        from gsv.visit.runner import run_subplan

        chosen = self.then_steps if await self.condition(ctx) else self.else_steps
        if not chosen:
            return StepResult(name=self.name, outcome="ok")
        sub_result = await run_subplan(ctx, chosen)
        return StepResult(
            name=self.name,
            outcome="ok" if sub_result.outcome == "completed" else "fail",
            error=sub_result.error,
            extracted=sub_result.counters,
        )


@dataclass
class ForEach:
    """Extract items and run per-item body steps."""

    items_extractor: Callable[[Any], Awaitable[list[Any]]]
    body_factory: Callable[[Any], list[VisitStep]]
    name: str = "for_each"
    content_marker: str | None = None
    max_items: int | None = None
    limit: int | None = None
    hydration_retry: bool = False
    hydration_delay_range: tuple[float, float] = (0.5, 1.5)

    async def execute(self, ctx: VisitContext) -> StepResult:
        """Run body steps for each extracted item."""
        from gsv.visit.runner import run_subplan

        items = await self.items_extractor(ctx.page)
        limited_items = items[: self._resolved_limit()]
        iteration_results: list[list[StepResult]] = []
        failed = False
        errors: list[str] = []

        for item in limited_items:
            body = self.body_factory(item)
            sub_result = await run_subplan(ctx, body)
            results = list(sub_result.step_results)
            if sub_result.outcome != "completed":
                failed = True
                if sub_result.error is not None:
                    errors.append(sub_result.error)
            if self.hydration_retry and self._needs_hydration_retry(results):
                ctx.increment("hydration_retry_attempts")
                await self._hydrate_item(ctx, item)
                retry_result = await run_subplan(ctx, self.body_factory(item))
                retry_results = list(retry_result.step_results)
                results.extend(retry_results)
                if self._needs_hydration_retry(retry_results) or retry_result.outcome != "completed":
                    ctx.increment("hydration_retry_giveup_count")
                    failed = True
                    if retry_result.error is not None:
                        errors.append(retry_result.error)
                    elif self._needs_hydration_retry(retry_results):
                        errors.append("hydration retry did not produce a viable item")
                else:
                    ctx.increment("hydration_retry_success_count")
            iteration_results.append(results)

        return StepResult(
            name=self.name,
            outcome="fail" if failed else "ok",
            error="; ".join(errors) if errors else None,
            extracted=iteration_results,
        )

    def _resolved_limit(self) -> int | None:
        if self.limit is not None:
            return self.limit
        return self.max_items

    @staticmethod
    def _needs_hydration_retry(results: list[StepResult]) -> bool:
        if not results:
            return False
        return bool(results[0].extracted == EmptyResult.HYDRATION_NEEDED)

    async def _hydrate_item(self, ctx: VisitContext, item: Any) -> None:
        locator = self._hydration_locator(ctx, item)
        if locator is not None:
            first = getattr(locator, "first", locator)
            await first.scroll_into_view_if_needed()
        await random_delay(*self.hydration_delay_range, rng=ctx.rng)

    @staticmethod
    def _hydration_locator(ctx: VisitContext, item: Any) -> Any | None:
        if hasattr(item, "scroll_into_view_if_needed"):
            return item
        if isinstance(item, Mapping):
            locator = item.get("locator")
            if locator is not None:
                return locator
            selector = item.get("selector")
            if isinstance(selector, str):
                return ctx.page.locator(selector)
        return None


@dataclass
class RecordEvent:
    """Write an app-defined event to the configured evidence sink."""

    event_type: str
    payload_factory: Callable[[VisitContext], Mapping[str, Any]]
    name: str = "record_event"
    content_marker: str | None = None

    async def execute(self, ctx: VisitContext) -> StepResult:
        """Record one structured event."""
        payload = self.payload_factory(ctx)
        await ctx.sink.write(self.event_type, payload)
        return StepResult(name=self.name, outcome="ok")
