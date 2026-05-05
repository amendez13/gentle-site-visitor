"""Tests for action steps."""

from __future__ import annotations

from typing import Any

import pytest

from gsv.visit.steps import Click, Dwell, Scroll, Type


@pytest.mark.asyncio
async def test_click_uses_jitter_when_configured(
    monkeypatch: pytest.MonkeyPatch,
    visit_ctx,  # type: ignore[no-untyped-def]
) -> None:
    """Click uses the S1 jitter primitive by default."""
    calls: list[tuple[Any, str]] = []

    async def fake_click(page: Any, selector: str, **_kwargs: Any) -> bool:
        calls.append((page, selector))
        return True

    monkeypatch.setattr("gsv.visit.steps.act.click_with_position_jitter", fake_click)

    result = await Click("#submit").execute(visit_ctx)

    assert result.outcome == "ok"
    assert calls == [(visit_ctx.page, "#submit")]


@pytest.mark.asyncio
async def test_click_can_skip_jitter_and_wait_after(fake_page, visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """Click supports a direct click and follow-up wait."""
    result = await Click("#submit", jitter=False, wait_for="#done").execute(visit_ctx)

    assert result.outcome == "ok"
    assert fake_page.clicks == ["#submit"]
    assert fake_page.waits == [("#done", None)]


@pytest.mark.asyncio
async def test_type_uses_human_type(monkeypatch: pytest.MonkeyPatch, visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """Type delegates to the S1 human_type primitive."""
    calls: list[tuple[Any, str, str]] = []

    async def fake_type(page: Any, selector: str, value: str, **_kwargs: Any) -> None:
        calls.append((page, selector, value))

    monkeypatch.setattr("gsv.visit.steps.act.human_type", fake_type)

    result = await Type("#q", "hello").execute(visit_ctx)

    assert result.outcome == "ok"
    assert calls == [(visit_ctx.page, "#q", "hello")]


@pytest.mark.asyncio
async def test_scroll_uses_scroll_page(monkeypatch: pytest.MonkeyPatch, visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """Scroll delegates to the S1 scroll primitive."""
    calls: list[tuple[Any, int]] = []

    async def fake_scroll(page: Any, *, times: int, **_kwargs: Any) -> None:
        calls.append((page, times))

    monkeypatch.setattr("gsv.visit.steps.act.scroll_page", fake_scroll)

    result = await Scroll(times=3).execute(visit_ctx)

    assert result.outcome == "ok"
    assert calls == [(visit_ctx.page, 3)]


@pytest.mark.asyncio
async def test_dwell_uses_humanized_dwell(monkeypatch: pytest.MonkeyPatch, visit_ctx) -> None:  # type: ignore[no-untyped-def]
    """Dwell delegates to the S1 dwell primitive and exposes elapsed seconds."""
    calls: list[tuple[Any, float, float]] = []

    async def fake_dwell(page: Any, *, min_seconds: float, max_seconds: float, **_kwargs: Any) -> float:
        calls.append((page, min_seconds, max_seconds))
        return 4.2

    monkeypatch.setattr("gsv.visit.steps.act.run_humanized_page_dwell", fake_dwell)

    result = await Dwell(min_seconds=1.0, max_seconds=2.0).execute(visit_ctx)

    assert result.outcome == "ok"
    assert result.extracted == 4.2
    assert calls == [(visit_ctx.page, 1.0, 2.0)]
