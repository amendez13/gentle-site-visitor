"""Session auth state machine."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any
from urllib.parse import urlparse

from gsv.browser.manager import BrowserManager
from gsv.browser.primitives import click_with_position_jitter, human_type, random_delay
from gsv.config.model import VisitorConfig
from gsv.session.adapter import SiteAuthAdapter
from gsv.session.challenge import ChallengePolicy
from gsv.session.credentials import Credentials
from gsv.session.diagnostics import log_login_diagnostics
from gsv.session.warmup import post_login_warmup as run_post_login_warmup

LOG = logging.getLogger(__name__)


class SessionAuthError(RuntimeError):
    """Raised when the session cannot attempt authentication safely."""


class Session:
    """Restore or establish an authenticated browser session for one site adapter."""

    def __init__(
        self,
        browser: BrowserManager,
        adapter: SiteAuthAdapter,
        config: VisitorConfig,
        *,
        challenge_policy: ChallengePolicy | None = None,
        rng: random.Random | None = None,
        auth_delay_range: tuple[float, float] = (0.5, 1.0),
        form_wait_timeout_ms: int = 3000,
        completion_timeout_ms: int = 15000,
    ) -> None:
        self.browser = browser
        self.adapter = adapter
        self.config = config
        self.challenge_policy = challenge_policy or ChallengePolicy(
            mode="headless" if config.headless else "headed",
            timeout_seconds=config.manual_verification_timeout_seconds,
        )
        self._rng = rng if rng is not None else random.Random()
        self._auth_delay_range = auth_delay_range
        self._form_wait_timeout_ms = max(1, form_wait_timeout_ms)
        self._completion_timeout_ms = max(1, completion_timeout_ms)
        self._page: Any | None = None
        self._authenticated = False
        self._warmup_done = False

    @property
    def is_authenticated(self) -> bool:
        """Return the last known authentication state."""
        return self._authenticated

    async def start(self) -> bool:
        """Start the browser and classify whether saved storage is authenticated."""
        await self._start_browser()
        page = await self._ensure_page()
        self._authenticated = await self._check_authenticated(page)
        if self._authenticated:
            LOG.info("Restored authenticated session")
        return self._authenticated

    async def login(  # noqa: C901 - keep the five-stage auth flow together.
        self, credentials: Credentials | None = None
    ) -> bool:
        """Run the adapter-driven login flow and persist storage on success."""
        page = await self._ensure_page()

        if not self.adapter.requires_credentials:
            self._authenticated = await self._complete_no_auth_flow(page)
            if self._authenticated:
                await self.browser.save_session()
            return self._authenticated

        if credentials is None:
            raise SessionAuthError("credentials are required for this adapter")

        await page.goto(self.adapter.login_target_url, wait_until="domcontentloaded")
        await self._auth_delay()

        if self.adapter.is_authenticated_url(str(page.url)):
            self._authenticated = True
            await self.browser.save_session()
            return True

        if self.adapter.is_challenge_url(str(page.url)):
            self._authenticated = await self.challenge_policy.handle(page, self.adapter.is_authenticated_url)
            if self._authenticated:
                await self.browser.save_session()
            return self._authenticated

        if not await self._prepare_login_page(page):
            await log_login_diagnostics(page, self.adapter, "credential_form_missing")
            return False
        if not await self._fill_credentials(page, credentials):
            await log_login_diagnostics(page, self.adapter, "credential_entry_failed")
            return False
        if not await self._submit_login_form(page):
            await log_login_diagnostics(page, self.adapter, "submit_failed")
            return False

        self._authenticated = await self._wait_for_login_completion(page)
        if self._authenticated:
            await self.browser.save_session()
        return self._authenticated

    async def post_login_warmup(self) -> bool:
        """Run the optional post-login warmup once per session object."""
        if self._warmup_done or not self.config.pacing.post_login_warmup or self.adapter.warmup_url is None:
            return False
        page = await self._ensure_page()
        ran = await run_post_login_warmup(page, self.adapter.warmup_url, rng=self._rng)
        self._warmup_done = bool(ran)
        return bool(ran)

    async def new_page(self) -> Any:
        """Create a fresh page from the managed browser context."""
        await self._start_browser()
        return await self.browser.new_page()

    async def close(self) -> None:
        """Close the underlying browser manager."""
        await self.browser.close()
        self._page = None

    async def _start_browser(self) -> None:
        if self.browser.context is not None:
            return
        context = await self.browser.start()
        for script in self.adapter.extra_init_scripts:
            await context.add_init_script(script)

    async def _ensure_page(self) -> Any:
        await self._start_browser()
        if self._page is None:
            self._page = await self.browser.new_page()
        return self._page

    async def _check_authenticated(self, page: Any) -> bool:
        try:
            await page.goto(self.adapter.auth_marker_url, wait_until="domcontentloaded")
            await self._auth_delay()
        except Exception:
            LOG.debug("Authentication marker check failed", exc_info=True)
            return False
        return bool(self.adapter.is_authenticated_url(str(page.url)))

    async def _complete_no_auth_flow(self, page: Any) -> bool:
        await page.goto(self.adapter.auth_marker_url, wait_until="domcontentloaded")
        await self._auth_delay()
        if self.adapter.is_challenge_url(str(page.url)):
            return bool(await self.challenge_policy.handle(page, self.adapter.is_authenticated_url))
        if not self.adapter.is_authenticated_url(str(page.url)):
            await log_login_diagnostics(page, self.adapter, "auth_marker_not_reached")
            return False
        return True

    async def _prepare_login_page(self, page: Any) -> bool:
        await self._try_click(page, self.adapter.cookie_consent_selectors)
        await self._try_click(page, self.adapter.variant_trigger_selectors)
        return await self._wait_for_any_selector(page, self.adapter.username_selectors)

    async def _fill_credentials(self, page: Any, credentials: Credentials) -> bool:
        if not await self._try_type(page, self.adapter.username_selectors, credentials.username):
            return False
        await self._auth_delay()
        if not await self._try_type(page, self.adapter.password_selectors, credentials.password):
            return False
        await self._auth_delay()
        return True

    async def _submit_login_form(self, page: Any) -> bool:
        clicked = await self._try_click(page, self.adapter.submit_selectors)
        if clicked:
            # TODO(S3): replace this temporary reaction delay with DelayProfile.auth.
            await self._auth_delay()
        return bool(clicked)

    async def _wait_for_login_completion(self, page: Any) -> bool:
        deadline = time.monotonic() + (self._completion_timeout_ms / 1000.0)
        login_url_seen_after = time.monotonic() + 0.25
        while time.monotonic() < deadline:
            url = str(page.url)
            if self.adapter.is_authenticated_url(url):
                return True
            if self.adapter.is_challenge_url(url):
                return bool(await self.challenge_policy.handle(page, self.adapter.is_authenticated_url))
            if self._is_login_url(url) and time.monotonic() >= login_url_seen_after:
                await log_login_diagnostics(page, self.adapter, "still_on_login")
                return False
            await asyncio.sleep(0.05)

        await log_login_diagnostics(page, self.adapter, "completion_timeout")
        return False

    async def _wait_for_any_selector(self, page: Any, selectors: tuple[str, ...]) -> bool:
        for selector in selectors:
            try:
                await page.wait_for_selector(selector, timeout=self._form_wait_timeout_ms, state="visible")
                return True
            except Exception:
                LOG.debug("Selector not visible during login preparation: %s", selector, exc_info=True)
        return False

    async def _try_click(self, page: Any, selectors: tuple[str, ...]) -> bool:
        for selector in selectors:
            try:
                if int(await page.locator(selector).count()) <= 0:
                    continue
                if await click_with_position_jitter(page, selector, timeout=self._form_wait_timeout_ms, rng=self._rng):
                    return True
            except Exception:
                LOG.debug("Click failed for auth selector %s", selector, exc_info=True)
        return False

    async def _try_type(self, page: Any, selectors: tuple[str, ...], value: str) -> bool:
        for selector in selectors:
            try:
                await page.wait_for_selector(selector, timeout=self._form_wait_timeout_ms, state="visible")
                await human_type(page, selector, value, rng=self._rng)
                return True
            except Exception:
                LOG.debug("Type failed for auth selector %s", selector, exc_info=True)
        return False

    async def _auth_delay(self) -> None:
        # TODO(S3): replace this temporary reaction delay with DelayProfile.auth.
        await random_delay(*self._auth_delay_range, rng=self._rng)

    def _is_login_url(self, url: str) -> bool:
        if not self.adapter.login_url:
            return False
        current = urlparse(url)
        login = urlparse(self.adapter.login_url)
        return bool(current.path == login.path)
