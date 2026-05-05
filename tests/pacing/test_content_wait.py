"""Tests for content-aware waits."""

from __future__ import annotations

from typing import Any

import pytest

from gsv.pacing import ContentAwareWait


class FakePage:
    """Minimal page surface for content wait tests."""

    def __init__(self) -> None:
        self.waits: list[tuple[str, int]] = []

    async def wait_for_selector(self, selector: str, *, timeout: int) -> None:
        self.waits.append((selector, timeout))


@pytest.mark.asyncio
async def test_content_wait_is_noop_without_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """No marker means no selector wait, delay, or mouse movement."""
    page = FakePage()
    delay_calls: list[tuple[float, float]] = []
    mouse_calls: list[Any] = []

    async def fake_delay(min_s: float, max_s: float, **_kwargs: Any) -> float:
        delay_calls.append((min_s, max_s))
        return 0.0

    async def fake_mouse(page_arg: Any, **_kwargs: Any) -> None:
        mouse_calls.append(page_arg)

    monkeypatch.setattr("gsv.pacing.content_wait.random_delay", fake_delay)
    monkeypatch.setattr("gsv.pacing.content_wait.random_mouse_move", fake_mouse)

    await ContentAwareWait(timeout_ms=500, reaction_range=(0.5, 1.5), with_mouse_move=True).maybe_run(page, None)

    assert page.waits == []
    assert delay_calls == []
    assert mouse_calls == []


@pytest.mark.asyncio
async def test_content_wait_runs_selector_delay_and_mouse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configured markers wait for content, react, and optionally move the mouse."""
    page = FakePage()
    delay_calls: list[tuple[float, float]] = []
    mouse_calls: list[Any] = []

    async def fake_delay(min_s: float, max_s: float, **_kwargs: Any) -> float:
        delay_calls.append((min_s, max_s))
        return 0.7

    async def fake_mouse(page_arg: Any, **_kwargs: Any) -> None:
        mouse_calls.append(page_arg)

    monkeypatch.setattr("gsv.pacing.content_wait.random_delay", fake_delay)
    monkeypatch.setattr("gsv.pacing.content_wait.random_mouse_move", fake_mouse)

    await ContentAwareWait(timeout_ms=750, reaction_range=(0.25, 0.75), with_mouse_move=True).maybe_run(page, "#ready")

    assert page.waits == [("#ready", 750)]
    assert delay_calls == [(0.25, 0.75)]
    assert mouse_calls == [page]


@pytest.mark.asyncio
async def test_content_wait_can_skip_mouse_move(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mouse movement is controlled by config."""
    page = FakePage()
    mouse_calls: list[Any] = []

    async def fake_delay(_min_s: float, _max_s: float, **_kwargs: Any) -> float:
        return 0.0

    async def fake_mouse(page_arg: Any, **_kwargs: Any) -> None:
        mouse_calls.append(page_arg)

    monkeypatch.setattr("gsv.pacing.content_wait.random_delay", fake_delay)
    monkeypatch.setattr("gsv.pacing.content_wait.random_mouse_move", fake_mouse)

    await ContentAwareWait(timeout_ms=750, reaction_range=(0.25, 0.75), with_mouse_move=False).maybe_run(page, "#ready")

    assert page.waits == [("#ready", 750)]
    assert mouse_calls == []


def test_content_wait_rejects_invalid_config() -> None:
    """Wait timeouts and reaction ranges must be usable non-negative values."""
    with pytest.raises(ValueError, match="timeout_ms"):
        ContentAwareWait(timeout_ms=0, reaction_range=(0.1, 0.2), with_mouse_move=True)
    with pytest.raises(ValueError, match="non-negative"):
        ContentAwareWait(timeout_ms=1, reaction_range=(-0.1, 0.2), with_mouse_move=True)
