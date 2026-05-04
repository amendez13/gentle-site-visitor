"""Sliding-window request rate limiter."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

LOG = logging.getLogger(__name__)


@dataclass
class RateLimiter:
    """Track request timestamps and enforce a per-hour ceiling."""

    max_per_hour: int = 90
    clock: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep
    _timestamps: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.max_per_hour < 1:
            raise ValueError("max_per_hour must be at least 1")

    def _prune(self) -> None:
        cutoff = self.clock() - 3600
        self._timestamps = [timestamp for timestamp in self._timestamps if timestamp > cutoff]

    @property
    def remaining(self) -> int:
        """Return available request slots in the current sliding window."""
        self._prune()
        return max(0, self.max_per_hour - len(self._timestamps))

    async def acquire(self) -> None:
        """Wait until a request slot is available, then consume it."""
        while True:
            now = self.clock()
            self._prune()
            if len(self._timestamps) < self.max_per_hour:
                self._timestamps.append(now)
                return

            oldest = self._timestamps[0]
            wait_seconds = max(0.0, oldest + 3600 - now + 1)
            LOG.warning("Rate limit reached, waiting %.0fs", wait_seconds)
            await self.sleeper(wait_seconds)
