"""Login diagnostics for selector-driven auth flows."""

from __future__ import annotations

import logging
from typing import Any

from gsv.session.adapter import SiteAuthAdapter

LOG = logging.getLogger(__name__)


async def _selector_count(page: Any, selector: str) -> int:
    try:
        return int(await page.locator(selector).count())
    except Exception:
        LOG.debug("Could not count selector %s", selector, exc_info=True)
        return 0


async def _counts_for(page: Any, selectors: tuple[str, ...]) -> dict[str, int]:
    return {selector: await _selector_count(page, selector) for selector in selectors}


async def log_login_diagnostics(page: Any, adapter: SiteAuthAdapter, reason: str) -> None:
    """Log selector counts and page context after a failed login flow."""
    try:
        title = await page.title()
    except Exception:
        title = ""
    LOG.error(
        "session.login.diagnostics reason=%s url=%s title=%s username_selectors=%s password_selectors=%s "
        "submit_selectors=%s cookie_consent_selectors=%s variant_trigger_selectors=%s",
        reason,
        getattr(page, "url", ""),
        title,
        await _counts_for(page, adapter.username_selectors),
        await _counts_for(page, adapter.password_selectors),
        await _counts_for(page, adapter.submit_selectors),
        await _counts_for(page, adapter.cookie_consent_selectors),
        await _counts_for(page, adapter.variant_trigger_selectors),
    )
