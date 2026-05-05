"""Shared fixtures for visit-layer tests."""

from __future__ import annotations

from typing import Any

import pytest

from gsv.visit import VisitContext


class FakeRateLimiter:
    """Rate limiter test double."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.acquired = 0

    async def acquire(self) -> None:
        self.acquired += 1
        self.events.append("rate_limit")


class FakeContentWait:
    """Content wait test double."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.calls: list[tuple[Any, str | None]] = []

    async def maybe_run(self, page: Any, marker: str | None) -> None:
        self.calls.append((page, marker))
        self.events.append("content_wait")


class FakeDelayProfile:
    """Delay profile test double."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.sleeps = 0

    async def sleep(self) -> float:
        self.sleeps += 1
        self.events.append("delay")
        return 0.0


class FakeBurst:
    """Burst governor test double."""

    def __init__(self, events: list[str] | None = None, *, cooldown: float = 0.0) -> None:
        self.events = events if events is not None else []
        self.cooldown = cooldown
        self.boundaries: list[str] = []
        self.reset_count = 0

    async def tick(self, *, boundary: str = "burst") -> float:
        self.boundaries.append(boundary)
        self.events.append("burst")
        return self.cooldown

    def reset(self) -> None:
        self.reset_count += 1
        self.events.append("burst_reset")


class FakePacing:
    """Pacing aggregate test double."""

    def __init__(self, events: list[str] | None = None, *, cooldown: float = 0.0) -> None:
        self.events = events if events is not None else []
        self.rate_limiter = FakeRateLimiter(self.events)
        self.content_wait = FakeContentWait(self.events)
        self.delay_profile = FakeDelayProfile(self.events)
        self.burst = FakeBurst(self.events, cooldown=cooldown)


class FakePage:
    """Small Playwright-like page double."""

    def __init__(self) -> None:
        self.gotos: list[tuple[str, str]] = []
        self.waits: list[tuple[str, int | None]] = []
        self.clicks: list[str] = []
        self.locators: dict[str, FakeLocator] = {}

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.gotos.append((url, wait_until))

    async def wait_for_selector(self, selector: str, *, timeout: int | None = None) -> None:
        self.waits.append((selector, timeout))

    async def click(self, selector: str) -> None:
        self.clicks.append(selector)

    def locator(self, selector: str) -> "FakeLocator":
        locator = self.locators.setdefault(selector, FakeLocator())
        return locator


class FakeLocator:
    """Locator double with Playwright's .first shape."""

    def __init__(self) -> None:
        self.first = self
        self.scrolled = 0

    async def scroll_into_view_if_needed(self) -> None:
        self.scrolled += 1


@pytest.fixture
def fake_page() -> FakePage:
    """Return a Playwright-like fake page."""
    return FakePage()


@pytest.fixture
def visit_ctx(fake_page: FakePage) -> VisitContext:
    """Return a visit context with no-op pacing."""
    return VisitContext(page=fake_page, pacing=FakePacing())  # type: ignore[arg-type]
