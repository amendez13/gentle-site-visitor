"""Tests for flow-control steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from gsv.visit import StepResult, VisitContext, VisitPlan, VisitRunner
from gsv.visit.steps import Branch, ForEach, RecordEvent


@dataclass
class NamedStep:
    """Step that records its name."""

    seen: list[str]
    name: str
    content_marker: str | None = None

    async def execute(self, _ctx: VisitContext) -> StepResult:
        self.seen.append(self.name)
        return StepResult(name=self.name, outcome="ok")


@pytest.mark.asyncio
async def test_branch_runs_only_then_subtree(visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """Branch executes only the selected true subtree."""
    seen: list[str] = []

    async def condition(_ctx: VisitContext) -> bool:
        return True

    result = await VisitRunner(visit_ctx).run(
        VisitPlan(
            [
                Branch(
                    condition,
                    then_steps=[NamedStep(seen, name="then")],
                    else_steps=[NamedStep(seen, name="else")],
                )
            ]
        )
    )

    assert result.outcome == "completed"
    assert seen == ["then"]
    assert result.counters["requests_made"] == 2


@pytest.mark.asyncio
async def test_branch_runs_only_else_subtree(visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """Branch executes only the selected false subtree."""
    seen: list[str] = []

    async def condition(_ctx: VisitContext) -> bool:
        return False

    await VisitRunner(visit_ctx).run(
        VisitPlan(
            [
                Branch(
                    condition,
                    then_steps=[NamedStep(seen, name="then")],
                    else_steps=[NamedStep(seen, name="else")],
                )
            ]
        )
    )

    assert seen == ["else"]


@pytest.mark.asyncio
async def test_for_each_respects_limit(visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """ForEach limit caps iteration count."""
    seen: list[int] = []

    async def items(_page: Any) -> list[int]:
        return [1, 2, 3, 4]

    def body(item: int) -> list[NamedStep]:
        return [NamedStep(seen, name=str(item))]

    await VisitRunner(visit_ctx).run(VisitPlan([ForEach(items, body, limit=3)]))

    assert seen == ["1", "2", "3"]


@pytest.mark.asyncio
async def test_for_each_fails_when_iteration_body_fails(visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """Nested subplan failure propagates through the ForEach parent result."""

    @dataclass
    class FailingStep:
        name: str = "failing"
        content_marker: str | None = None

        async def execute(self, _ctx: VisitContext) -> StepResult:
            raise RuntimeError("extract failed")

    async def items(_page: Any) -> list[int]:
        return [1]

    result = await VisitRunner(visit_ctx).run(VisitPlan([ForEach(items, lambda _item: [FailingStep()])]))

    assert result.outcome == "failed"
    assert result.error == "extract failed"
    assert result.step_results[0].outcome == "fail"


@pytest.mark.asyncio
async def test_record_event_writes_to_sink(visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """RecordEvent writes through the configured evidence sink."""
    events: list[tuple[str, dict[str, Any]]] = []

    class Sink:
        async def write(self, event_type: str, payload: dict[str, Any]) -> None:
            events.append((event_type, payload))

    visit_ctx.sink = Sink()
    visit_ctx.extracted["count"] = 2

    result = await RecordEvent("counted", lambda ctx: {"count": ctx.extracted["count"]}).execute(visit_ctx)

    assert result.outcome == "ok"
    assert events == [("counted", {"count": 2})]
