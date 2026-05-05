"""Playwright browser/context manager for site visits."""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any, cast

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from gsv.browser.fingerprint import build_user_agent, build_viewport
from gsv.browser.primitives import STEALTH_LAUNCH_ARGS, WEBDRIVER_INIT_SCRIPT
from gsv.browser.rate_limit import RateLimiter
from gsv.browser.recording import BrowserRecording
from gsv.config.model import RateLimitConfig, SiteConfig, VisitorConfig
from gsv.observability import SessionRecorder

LOG = logging.getLogger(__name__)


class BrowserManager:
    """Manage a Playwright Chromium browser with persisted storage state."""

    def __init__(
        self,
        visitor_config: VisitorConfig,
        site_config: SiteConfig,
        *,
        rng: random.Random | None = None,
    ) -> None:
        self.visitor = visitor_config
        self.site = site_config
        self._rng = rng if rng is not None else random.Random()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._last_viewport: dict[str, int] = {}
        self._recording: BrowserRecording = BrowserRecording(self)
        self.rate_limiter = RateLimiter(config=self._effective_rate_limit())

    @property
    def context(self) -> BrowserContext | None:
        """Return the active browser context, if started."""
        return self._context

    def _effective_rate_limit(self) -> RateLimitConfig:
        """Return the per-site override or visitor-level default rate limit."""
        if self.site.rate_limit is not None:
            return self.site.rate_limit
        return RateLimitConfig(requests_per_hour=self.visitor.pacing.rate_limit_per_hour)

    def get_browser_metadata(self) -> dict[str, Any]:
        """Return browser config snapshot for later session manifests."""
        browser_version = str(getattr(self._browser, "version", "") or "")
        return {
            "chromium_version": browser_version,
            "user_agent": build_user_agent(browser_version),
            "headless": self.visitor.headless,
            "viewport": dict(self._last_viewport),
            "locale": self.site.locale,
            "timezone_id": self.site.timezone_id,
        }

    def attach_recorder(self, recorder: SessionRecorder | None) -> None:
        """Attach an observability recorder for trace/HAR/video artifacts."""
        self._recording.attach_recorder(recorder)

    async def start_tracing(self) -> None:
        """Begin Playwright tracing for the active recorder, if configured."""
        await self._recording.start_tracing()

    async def stop_tracing(self) -> str | None:
        """Stop Playwright tracing and return the trace path."""
        return cast(str | None, await self._recording.stop_tracing())

    async def enable_har_for_session(self) -> None:
        """Rotate the context to enable HAR/video recording."""
        await self._recording.enable_har_for_session()

    async def finalize_har(self) -> str | None:
        """Flush HAR/video recording and rotate back to a baseline context."""
        return cast(str | None, await self._recording.finalize_har())

    def finalize_video(self) -> str | None:
        """Promote recorded videos into canonical session artifact names."""
        return cast(str | None, self._recording.finalize_video())

    @property
    def har_path(self) -> str | None:
        """Return the active HAR path, if recording is enabled."""
        return cast(str | None, self._recording.har_path)

    def cleanup_artifacts_on_success(self) -> None:
        """Remove heavy artifacts after successful failures-mode runs."""
        self._recording.cleanup_artifacts_on_success()

    def _build_context_kwargs(
        self,
        storage_state: Any = None,
        *,
        har_path: str | None = None,
        video_dir: Path | None = None,
        viewport: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Build kwargs for browser.new_context()."""
        browser_version = str(getattr(self._browser, "version", "") or "")
        selected_viewport = (
            dict(viewport)
            if viewport is not None
            else build_viewport(
                self._rng,
                self.visitor.fingerprint.viewport_width_range,
                self.visitor.fingerprint.viewport_height_range,
            )
        )
        self._last_viewport = dict(selected_viewport)
        kwargs: dict[str, Any] = {
            "storage_state": storage_state,
            "viewport": selected_viewport,
            "locale": self.site.locale,
            "timezone_id": self.site.timezone_id,
            "user_agent": build_user_agent(browser_version),
        }
        if har_path:
            kwargs["record_har_path"] = har_path
            if self.site.allowed_host_globs:
                kwargs["record_har_url_filter"] = self.site.allowed_host_globs[0]
            if self.visitor.observability.har_content == "omit":
                kwargs["record_har_content"] = "omit"
        if video_dir:
            kwargs["record_video_dir"] = str(video_dir)
            kwargs["record_video_size"] = {"width": 1280, "height": 800}
        return kwargs

    async def _apply_context_defaults(self) -> None:
        """Inject init scripts and set the default page timeout."""
        if not self._context:
            return
        await self._context.add_init_script(WEBDRIVER_INIT_SCRIPT)
        self._context.set_default_timeout(self.site.page_timeout_seconds * 1000)

    async def start(self) -> BrowserContext:
        """Launch Chromium and create a context with optional saved storage state."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.visitor.headless,
            args=STEALTH_LAUNCH_ARGS,
        )

        storage_state: str | None = None
        storage_dir = self.site.storage_dir
        if storage_dir is not None:
            session_file = storage_dir / "state.json"
            if session_file.exists():
                storage_state = str(session_file)
                LOG.info("Loading saved session from %s", session_file)

        self._context = await self._browser.new_context(**self._build_context_kwargs(storage_state))
        await self._apply_context_defaults()
        return self._context

    async def save_session(self) -> None:
        """Persist browser cookies/storage to the configured site directory."""
        if not self._context:
            return
        storage_dir = self.site.storage_dir
        if storage_dir is None:
            return
        storage_dir.mkdir(parents=True, exist_ok=True)
        session_file = storage_dir / "state.json"
        try:
            state = await self._context.storage_state()
        except Exception:
            LOG.debug("Could not read storage state; browser context may already be closed", exc_info=True)
            return
        session_file.write_text(json.dumps(state), encoding="utf-8")
        LOG.info("Session saved to %s", session_file)

    async def new_page(self) -> Page:
        """Create a page after acquiring a rate-limit slot."""
        if not self._context:
            raise RuntimeError("Browser not started; call start() first")
        await self.rate_limiter.acquire()
        return await self._context.new_page()

    async def close(self) -> None:
        """Close browser context, browser, and Playwright runtime."""
        await self.stop_tracing()
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
