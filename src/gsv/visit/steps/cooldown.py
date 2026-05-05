"""Explicit burst cooldown steps."""

from __future__ import annotations

from dataclasses import dataclass

from gsv.visit.context import VisitContext
from gsv.visit.plan import StepResult


@dataclass
class BurstCooldown:
    """Hint or reset the burst governor at a logical section boundary."""

    reset: bool = False
    name: str = "burst_cooldown"
    content_marker: str | None = None
    skip_runner_burst_tick: bool = True

    async def execute(self, ctx: VisitContext) -> StepResult:
        """Trigger an explicit burst tick or reset the counter."""
        if self.reset:
            ctx.pacing.burst.reset()
        else:
            cooldown = await ctx.pacing.burst.tick(boundary="explicit_cooldown")
            if cooldown > 0:
                ctx.increment("cooldowns")
        return StepResult(name=self.name, outcome="ok")
