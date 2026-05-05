"""Visit runner that applies the canonical docs/ARCHITECTURE.md section 4.4 wrap."""

from __future__ import annotations

import asyncio
import time

from gsv.visit.context import VisitContext, VisitResult
from gsv.visit.plan import StepResult, VisitPlan, VisitStep


class VisitRunner:
    """Run visit plans while applying pacing, rate limiting, and cancellation seams."""

    def __init__(
        self,
        ctx: VisitContext,
        *,
        update_recorder: bool = True,
        propagate_cancellation: bool = False,
    ) -> None:
        self.ctx = ctx
        self.update_recorder = update_recorder
        self.propagate_cancellation = propagate_cancellation

    async def run(self, plan: VisitPlan) -> VisitResult:
        """Run a plan and return the aggregate result."""
        step_results: list[StepResult] = []
        try:
            await self._run_plan(plan, step_results)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self.propagate_cancellation and self._looks_like_cancellation(exc):
                raise
            result = VisitResult(
                outcome="cancelled" if self._looks_like_cancellation(exc) else "failed",
                error=str(exc),
                counters=dict(self.ctx.counters),
                extracted=dict(self.ctx.extracted),
                step_results=step_results,
            )
            self._update_recorder(result)
            return result

        outcome = plan.classify(step_results)
        result = VisitResult(
            outcome=outcome,
            error=self._first_error(step_results),
            counters=dict(self.ctx.counters),
            extracted=dict(self.ctx.extracted),
            step_results=step_results,
        )
        self._update_recorder(result)
        return result

    async def _run_plan(self, plan: VisitPlan, step_results: list[StepResult]) -> None:
        for item in plan.steps:
            if isinstance(item, VisitPlan):
                await self._run_plan(item, step_results)
                continue
            step_results.append(await self._run_step(item))

    async def _run_step(self, step: VisitStep) -> StepResult:
        await self._cancel_check(f"{step.name}_pre")
        await self.ctx.pacing.rate_limiter.acquire()
        self.ctx.increment("requests_made")

        start = time.monotonic()
        try:
            result = await step.execute(self.ctx)
        except Exception as exc:
            result = StepResult(name=step.name, outcome="fail", error=str(exc))

        await self.ctx.pacing.content_wait.maybe_run(self.ctx.page, step.content_marker)
        await self.ctx.pacing.delay_profile.sleep()
        if not bool(getattr(step, "skip_runner_burst_tick", False)):
            cooldown = await self.ctx.pacing.burst.tick(boundary=f"{step.name}_burst")
            if cooldown > 0:
                self.ctx.increment("cooldowns")
        await self._cancel_check(f"{step.name}_post")

        result.duration_seconds = time.monotonic() - start
        return result

    async def _cancel_check(self, boundary: str) -> None:
        if self.ctx.cancellation is None:
            return
        self.ctx.increment("cancellation_checks_visited")
        await self.ctx.cancellation.check(boundary=boundary)

    @staticmethod
    def _first_error(step_results: list[StepResult]) -> str | None:
        for result in step_results:
            if result.error:
                return str(result.error)
        return None

    @staticmethod
    def _looks_like_cancellation(exc: Exception) -> bool:
        name = str(exc.__class__.__name__)
        return name == "RunCancellationRequested" or "cancel" in name.lower()

    def _update_recorder(self, result: VisitResult) -> None:
        if not self.update_recorder or self.ctx.recorder is None:
            return
        self.ctx.recorder.update_counters(**result.counters)


async def run_subplan(ctx: VisitContext, steps: list[VisitStep]) -> VisitResult:
    """Run a nested list of steps with the same wrapping semantics as top-level steps."""
    return await VisitRunner(ctx, update_recorder=False).run(VisitPlan(steps=steps))
