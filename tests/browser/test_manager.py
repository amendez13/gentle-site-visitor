"""Tests for the Playwright BrowserManager wrapper."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

from gsv.browser.manager import BrowserManager
from gsv.browser.primitives import STEALTH_LAUNCH_ARGS, WEBDRIVER_INIT_SCRIPT
from gsv.config import FingerprintConfig, ObservabilityConfig, PacingConfig, SiteConfig, VisitorConfig


class FakeContext:
    """Fake Playwright browser context."""

    def __init__(self, storage_state_payload: dict[str, Any] | None = None) -> None:
        self.init_scripts: list[str] = []
        self.default_timeout: int | None = None
        self.closed = False
        self.pages_created = 0
        self.storage_state_payload = storage_state_payload or {"cookies": [], "origins": []}

    async def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)

    def set_default_timeout(self, timeout: int) -> None:
        self.default_timeout = timeout

    async def storage_state(self) -> dict[str, Any]:
        return self.storage_state_payload

    async def new_page(self) -> object:
        self.pages_created += 1
        return object()

    async def close(self) -> None:
        self.closed = True


class FailingStorageContext(FakeContext):
    """Context whose storage state cannot be read."""

    async def storage_state(self) -> dict[str, Any]:
        raise RuntimeError("closed")


class FakeBrowser:
    """Fake Playwright browser."""

    version = "Chromium 123.4.5.6"

    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.context_kwargs: list[dict[str, Any]] = []
        self.closed = False

    async def new_context(self, **kwargs: Any) -> FakeContext:
        self.context_kwargs.append(kwargs)
        return self.context

    async def close(self) -> None:
        self.closed = True


class FakeChromium:
    """Fake chromium launcher."""

    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.launch_kwargs: dict[str, Any] | None = None

    async def launch(self, **kwargs: Any) -> FakeBrowser:
        self.launch_kwargs = kwargs
        return self.browser


class FakePlaywright:
    """Fake Playwright runtime."""

    def __init__(self, browser: FakeBrowser) -> None:
        self.chromium = FakeChromium(browser)
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class FakePlaywrightStarter:
    """Fake async_playwright context manager factory."""

    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright

    async def start(self) -> FakePlaywright:
        return self.playwright


def build_manager(tmp_path: Path) -> BrowserManager:
    """Create a manager with deterministic viewport settings."""
    visitor = VisitorConfig(
        headless=True,
        pacing=PacingConfig(rate_limit_per_hour=3),
        fingerprint=FingerprintConfig(viewport_width_range=(100, 100), viewport_height_range=(200, 200)),
    )
    site = SiteConfig(
        name="example",
        storage_path=str(tmp_path),
        locale="en-GB",
        timezone_id="Europe/London",
        page_timeout_seconds=12,
        allowed_host_globs=["**/*.example.test/**"],
    )
    return BrowserManager(visitor, site, rng=random.Random(1))


@pytest.mark.asyncio
async def test_start_launches_context_and_loads_storage_state(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """start launches Chromium, loads state.json, and applies context defaults."""
    state_file = tmp_path / "state.json"
    state_file.write_text('{"cookies": []}', encoding="utf-8")
    context = FakeContext()
    browser = FakeBrowser(context)
    playwright = FakePlaywright(browser)
    manager = build_manager(tmp_path)

    monkeypatch.setattr("gsv.browser.manager.async_playwright", lambda: FakePlaywrightStarter(playwright))

    started_context = await manager.start()

    assert started_context is context
    assert playwright.chromium.launch_kwargs == {
        "headless": True,
        "args": STEALTH_LAUNCH_ARGS,
    }
    kwargs = browser.context_kwargs[0]
    assert kwargs["storage_state"] == str(state_file)
    assert kwargs["viewport"] == {"width": 100, "height": 200}
    assert kwargs["locale"] == "en-GB"
    assert kwargs["timezone_id"] == "Europe/London"
    assert "Chrome/123.4.5.6" in kwargs["user_agent"]
    assert context.init_scripts == [WEBDRIVER_INIT_SCRIPT]
    assert context.default_timeout == 12000

    await manager.close()

    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


def test_build_context_kwargs_uses_site_har_filter(tmp_path) -> None:
    """HAR-specific context kwargs use allowed_host_globs instead of hardcoded hosts."""
    manager = build_manager(tmp_path)
    manager._browser = FakeBrowser(FakeContext())  # type: ignore[assignment]

    kwargs = manager._build_context_kwargs({"cookies": []}, har_path="/tmp/network.har", video_dir=tmp_path / "videos")

    assert kwargs["storage_state"] == {"cookies": []}
    assert kwargs["record_har_path"] == "/tmp/network.har"
    assert kwargs["record_har_url_filter"] == "**/*.example.test/**"
    assert kwargs["record_har_content"] == "omit"
    assert kwargs["record_video_dir"] == str(tmp_path / "videos")
    assert kwargs["record_video_size"] == {"width": 1280, "height": 800}


def test_build_context_kwargs_allows_embed_har_without_host_filter(tmp_path) -> None:
    """HAR kwargs omit optional filters when the site/config does not request them."""
    visitor = VisitorConfig(observability=ObservabilityConfig(har_content="embed"))
    site = SiteConfig(name="example", storage_path=str(tmp_path), allowed_host_globs=[])
    manager = BrowserManager(visitor, site, rng=random.Random(1))

    kwargs = manager._build_context_kwargs(har_path="/tmp/network.har")

    assert kwargs["record_har_path"] == "/tmp/network.har"
    assert "record_har_url_filter" not in kwargs
    assert "record_har_content" not in kwargs


@pytest.mark.asyncio
async def test_apply_context_defaults_noops_without_context(tmp_path) -> None:
    """Applying defaults before start is harmless."""
    manager = build_manager(tmp_path)

    assert manager.context is None
    await manager._apply_context_defaults()


@pytest.mark.asyncio
async def test_save_session_writes_storage_state(tmp_path) -> None:
    """save_session persists the active context storage_state."""
    manager = build_manager(tmp_path)
    manager._context = FakeContext({"cookies": [{"name": "session", "value": "1"}], "origins": []})  # type: ignore[assignment]

    await manager.save_session()

    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8")) == {
        "cookies": [{"name": "session", "value": "1"}],
        "origins": [],
    }


@pytest.mark.asyncio
async def test_save_session_noops_without_context_or_storage(tmp_path) -> None:
    """save_session tolerates inactive contexts and disabled storage."""
    manager = build_manager(tmp_path)
    await manager.save_session()

    site = SiteConfig(name="example", storage_path="")
    disabled_storage = BrowserManager(VisitorConfig(), site)
    disabled_storage._context = FakeContext()  # type: ignore[assignment]

    await disabled_storage.save_session()

    assert not (tmp_path / "state.json").exists()


@pytest.mark.asyncio
async def test_save_session_ignores_closed_context(tmp_path) -> None:
    """A context that can no longer report storage state is not fatal."""
    manager = build_manager(tmp_path)
    manager._context = FailingStorageContext()  # type: ignore[assignment]

    await manager.save_session()

    assert not (tmp_path / "state.json").exists()


@pytest.mark.asyncio
async def test_new_page_requires_started_context_and_acquires_rate_limit(tmp_path) -> None:
    """new_page refuses to run before start and consumes a rate-limit slot afterward."""
    manager = build_manager(tmp_path)
    with pytest.raises(RuntimeError, match="Browser not started"):
        await manager.new_page()

    context = FakeContext()
    manager._context = context  # type: ignore[assignment]

    page = await manager.new_page()

    assert page is not None
    assert context.pages_created == 1
    assert manager.rate_limiter.remaining == 2


def test_get_browser_metadata_uses_browser_version(tmp_path) -> None:
    """Browser metadata is ready for S5 session manifests."""
    manager = build_manager(tmp_path)
    manager._browser = FakeBrowser(FakeContext())  # type: ignore[assignment]

    metadata = manager.get_browser_metadata()

    assert metadata["chromium_version"] == "Chromium 123.4.5.6"
    assert "Chrome/123.4.5.6" in metadata["user_agent"]
    assert metadata["locale"] == "en-GB"
