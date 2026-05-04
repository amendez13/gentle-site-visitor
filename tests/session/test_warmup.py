"""Tests for post-login warmup behavior."""

from __future__ import annotations

import random
from typing import Any

import pytest

from gsv.config import PacingConfig, VisitorConfig
from gsv.session import Session, SiteAuthAdapter
from gsv.session.warmup import post_login_warmup


class FakeMouse:
    """Fake Playwright mouse."""

    async def move(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class FakeWarmupPage:
    """Fake page that records navigation and scrolling."""

    viewport_size = {"width": 1000, "height": 800}

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.scrolls = 0
        self.mouse = FakeMouse()

    async def goto(self, url: str, **_kwargs: Any) -> None:
        self.urls.append(url)

    async def evaluate(self, *_args: Any) -> None:
        self.scrolls += 1


class FakeBrowserManager:
    """Minimal browser manager for session warmup tests."""

    def __init__(self, page: FakeWarmupPage) -> None:
        self.context = object()
        self.page = page
        self.pages_created = 0

    async def start(self) -> object:
        return self.context

    async def new_page(self) -> FakeWarmupPage:
        self.pages_created += 1
        return self.page

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_warmup_helper_noops_without_url() -> None:
    """The helper does no browser work without a configured URL."""
    page = FakeWarmupPage()

    ran = await post_login_warmup(page, None, rng=random.Random(1))

    assert ran is False
    assert page.urls == []


@pytest.mark.asyncio
async def test_warmup_helper_navigates_and_scrolls() -> None:
    """The helper performs a short read path with deterministic ranges."""
    page = FakeWarmupPage()

    ran = await post_login_warmup(
        page,
        "https://example.test/home",
        initial_delay_range=(0, 0),
        scroll_count_range=(2, 2),
        closing_delay_range=(0, 0),
        rng=random.Random(1),
    )

    assert ran is True
    assert page.urls == ["https://example.test/home"]
    assert page.scrolls == 2


@pytest.mark.asyncio
async def test_session_warmup_is_idempotent(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A session runs warmup only once even when called repeatedly."""
    page = FakeWarmupPage()
    browser = FakeBrowserManager(page)
    calls: list[str] = []

    async def fake_warmup(page_arg: FakeWarmupPage, warmup_url: str, **_kwargs: Any) -> bool:
        calls.append(warmup_url)
        await page_arg.goto(warmup_url)
        return True

    monkeypatch.setattr("gsv.session.runner.run_post_login_warmup", fake_warmup)
    session = Session(
        browser,  # type: ignore[arg-type]
        SiteAuthAdapter(auth_marker_url="https://example.test/home", warmup_url="https://example.test/home"),
        VisitorConfig(pacing=PacingConfig(post_login_warmup=True)),
        auth_delay_range=(0, 0),
    )

    first = await session.post_login_warmup()
    second = await session.post_login_warmup()

    assert first is True
    assert second is False
    assert calls == ["https://example.test/home"]
    assert browser.pages_created == 1
