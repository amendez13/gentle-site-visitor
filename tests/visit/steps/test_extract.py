"""Tests for extraction steps."""

from __future__ import annotations

import pytest

from gsv.visit import VisitPlan, VisitRunner
from gsv.visit.steps import Extract


@pytest.mark.asyncio
async def test_extract_populates_context_and_visit_result(visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """Extractor values are stored in the context and final result."""

    async def extractor(page):  # type: ignore[no-untyped-def]
        assert page is visit_ctx.page
        return {"title": "Example"}

    result = await VisitRunner(visit_ctx).run(VisitPlan([Extract(extractor, output_key="payload")]))

    assert result.outcome == "completed"
    assert visit_ctx.extracted["payload"] == {"title": "Example"}
    assert result.extracted["payload"] == {"title": "Example"}
    assert result.step_results[0].extracted == {"title": "Example"}
