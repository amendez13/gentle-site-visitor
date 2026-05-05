"""Stub app module imported by CLI run tests."""

from __future__ import annotations

from gsv.apps import register_app
from gsv.visit import StepResult, VisitContext, VisitPlan


class StubStep:
    """A no-op visit step."""

    name = "stub"
    content_marker = None

    async def execute(self, ctx: VisitContext) -> StepResult:
        """Record that the stub plan ran."""
        ctx.increment("stub_steps")
        return StepResult(name=self.name, outcome="ok")


def build_plan(ctx: VisitContext) -> VisitPlan:
    """Build a one-step plan."""
    del ctx
    return VisitPlan(steps=[StubStep()])


register_app("example", build_plan)
