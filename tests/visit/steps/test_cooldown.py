"""Tests for explicit burst cooldown steps."""

from __future__ import annotations

import pytest

from gsv.visit import VisitPlan, VisitRunner
from gsv.visit.steps import BurstCooldown


@pytest.mark.asyncio
async def test_burst_cooldown_triggers_burst_tick(visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """BurstCooldown can explicitly tick the burst governor."""
    visit_ctx.pacing.burst.cooldown = 7.0

    result = await BurstCooldown().execute(visit_ctx)

    assert result.outcome == "ok"
    assert visit_ctx.pacing.burst.boundaries == ["explicit_cooldown"]
    assert visit_ctx.counters["cooldowns"] == 1


@pytest.mark.asyncio
async def test_burst_cooldown_can_reset(visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """BurstCooldown can reset burst state without ticking."""
    result = await BurstCooldown(reset=True).execute(visit_ctx)

    assert result.outcome == "ok"
    assert visit_ctx.pacing.burst.reset_count == 1
    assert visit_ctx.pacing.burst.boundaries == []


@pytest.mark.asyncio
async def test_burst_cooldown_does_not_double_tick_inside_runner(visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """The explicit cooldown step owns its burst tick and skips the wrapper tick."""
    await VisitRunner(visit_ctx).run(VisitPlan([BurstCooldown()]))

    assert visit_ctx.pacing.burst.boundaries == ["explicit_cooldown"]


@pytest.mark.asyncio
async def test_burst_cooldown_reset_does_not_tick_inside_runner(visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """A reset step is not immediately offset by the wrapper burst tick."""
    await VisitRunner(visit_ctx).run(VisitPlan([BurstCooldown(reset=True)]))

    assert visit_ctx.pacing.burst.reset_count == 1
    assert visit_ctx.pacing.burst.boundaries == []
