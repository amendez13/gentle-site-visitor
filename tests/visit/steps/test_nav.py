"""Tests for navigation steps."""

from __future__ import annotations

import pytest

from gsv.visit.steps import Navigate, WaitFor


@pytest.mark.asyncio
async def test_navigate_calls_page_goto(fake_page) -> None:  # type: ignore[no-untyped-def]
    """Navigate forwards URL and wait mode."""
    result = await Navigate("https://example.test", wait_until="load").execute(fake_page_ctx(fake_page))

    assert result.outcome == "ok"
    assert fake_page.gotos == [("https://example.test", "load")]


@pytest.mark.asyncio
async def test_wait_for_uses_timeout(fake_page, visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """WaitFor forwards selector and timeout."""
    result = await WaitFor("#ready", timeout_ms=1234).execute(visit_ctx)

    assert result.outcome == "ok"
    assert fake_page.waits == [("#ready", 1234)]


@pytest.mark.asyncio
async def test_wait_for_retries_and_counts_hydration_retries(visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """Configured retries increment the issue-level hydration retry counter."""
    attempts = 0

    async def flaky_wait(selector: str, *, timeout: int | None = None) -> None:
        nonlocal attempts
        del selector, timeout
        attempts += 1
        if attempts < 3:
            raise RuntimeError("not ready")

    visit_ctx.page.wait_for_selector = flaky_wait

    result = await WaitFor("#ready", timeout_ms=1, retries=2).execute(visit_ctx)

    assert result.outcome == "ok"
    assert attempts == 3
    assert visit_ctx.counters["hydration_retries"] == 2


def fake_page_ctx(fake_page):  # type: ignore[no-untyped-def]
    """Build a context lazily to keep this test file focused."""
    from gsv.visit import VisitContext
    from tests.visit.conftest import FakePacing

    return VisitContext(page=fake_page, pacing=FakePacing())  # type: ignore[arg-type]
