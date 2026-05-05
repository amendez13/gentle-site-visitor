"""Tests for ForEach hydration retry handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from gsv.visit import StepResult, VisitContext, VisitPlan, VisitRunner
from gsv.visit.steps import EmptyResult, ForEach


@dataclass
class HydratingStep:
    """Step that needs hydration once per item."""

    item: dict[str, Any]
    attempts: dict[int, int]
    name: str = "extract_item"
    content_marker: str | None = None

    async def execute(self, _ctx: VisitContext) -> StepResult:
        item_id = int(self.item["id"])
        self.attempts[item_id] = self.attempts.get(item_id, 0) + 1
        if self.attempts[item_id] == 1:
            return StepResult(name=self.name, outcome="ok", extracted=EmptyResult.HYDRATION_NEEDED)
        return StepResult(name=self.name, outcome="ok", extracted={"id": item_id})


@pytest.mark.asyncio
async def test_for_each_hydration_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    visit_ctx,  # type: ignore[no-untyped-def]
) -> None:
    """Hydration retry scrolls the item into view, retries once, and counts success."""
    delays: list[tuple[float, float]] = []
    attempts: dict[int, int] = {}

    async def fake_delay(min_s: float, max_s: float, **_kwargs: Any) -> float:
        delays.append((min_s, max_s))
        return 0.0

    async def items(_page: Any) -> list[dict[str, Any]]:
        return [{"id": 1, "selector": "#item-1"}]

    def body(item: dict[str, Any]) -> list[HydratingStep]:
        return [HydratingStep(item, attempts)]

    monkeypatch.setattr("gsv.visit.steps.flow.random_delay", fake_delay)

    result = await VisitRunner(visit_ctx).run(VisitPlan([ForEach(items, body, hydration_retry=True)]))

    assert result.outcome == "completed"
    assert visit_ctx.counters["hydration_retry_attempts"] == 1
    assert visit_ctx.counters["hydration_retry_success_count"] == 1
    assert visit_ctx.page.locator("#item-1").scrolled == 1
    assert delays == [(0.5, 1.5)]


@pytest.mark.asyncio
async def test_for_each_hydration_retry_gives_up(
    monkeypatch: pytest.MonkeyPatch,
    visit_ctx,  # type: ignore[no-untyped-def]
) -> None:
    """Hydration retry records give-up when retry still needs hydration."""

    @dataclass
    class AlwaysNeedsHydration:
        name: str = "extract_item"
        content_marker: str | None = None

        async def execute(self, _ctx: VisitContext) -> StepResult:
            return StepResult(name=self.name, outcome="ok", extracted=EmptyResult.HYDRATION_NEEDED)

    async def fake_delay(_min_s: float, _max_s: float, **_kwargs: Any) -> float:
        return 0.0

    async def items(_page: Any) -> list[dict[str, Any]]:
        return [{"id": 1}]

    monkeypatch.setattr("gsv.visit.steps.flow.random_delay", fake_delay)

    await VisitRunner(visit_ctx).run(VisitPlan([ForEach(items, lambda _item: [AlwaysNeedsHydration()], hydration_retry=True)]))

    assert visit_ctx.counters["hydration_retry_attempts"] == 1
    assert visit_ctx.counters["hydration_retry_giveup_count"] == 1
