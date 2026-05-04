"""Manual verification challenge policy."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Literal

LOG = logging.getLogger(__name__)


class ChallengePolicy:
    """Handle manual verification challenges in headed and headless browser modes."""

    def __init__(
        self,
        *,
        mode: Literal["headed", "headless"],
        timeout_seconds: int,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        if mode not in {"headed", "headless"}:
            raise ValueError("mode must be 'headed' or 'headless'")
        self.mode = mode
        self.timeout_seconds = max(1, timeout_seconds)
        self.poll_interval_seconds = max(0.0, poll_interval_seconds)

    @classmethod
    def headed_wait(cls, *, timeout_seconds: int = 300, poll_interval_seconds: float = 1.0) -> "ChallengePolicy":
        """Build a policy that waits for an operator to complete verification."""
        return cls(mode="headed", timeout_seconds=timeout_seconds, poll_interval_seconds=poll_interval_seconds)

    @classmethod
    def headless_fail(cls, *, timeout_seconds: int = 300) -> "ChallengePolicy":
        """Build a policy that fails immediately in headless environments."""
        return cls(mode="headless", timeout_seconds=timeout_seconds)

    async def handle(self, page: Any, auth_marker_predicate: Callable[[str], bool]) -> bool:
        """Return whether a challenge resolves into an authenticated URL."""
        if auth_marker_predicate(str(page.url)):
            return True
        if self.mode == "headless":
            LOG.warning("Manual verification challenge encountered in headless mode; failing login")
            return False

        LOG.info("Manual verification challenge encountered; waiting up to %s seconds", self.timeout_seconds)
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            await asyncio.sleep(self.poll_interval_seconds)
            if auth_marker_predicate(str(page.url)):
                return True
        LOG.warning("Manual verification challenge did not complete before timeout")
        return False
