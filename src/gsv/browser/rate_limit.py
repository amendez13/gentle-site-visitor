"""Sliding-window request rate limiter."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from gsv.config.model import RateLimitConfig

LOG = logging.getLogger(__name__)


@dataclass
class RateLimiter:
    """Track request timestamps and enforce an hourly cap plus a smoothing window."""

    max_per_hour: int = 90
    window_minutes: int = 60
    config: RateLimitConfig | None = None
    clock: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep
    _timestamps: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.config is not None:
            self.max_per_hour = self.config.requests_per_hour
            self.window_minutes = self.config.window_minutes
        if self.max_per_hour < 1:
            raise ValueError("max_per_hour must be at least 1")
        if self.window_minutes < 1:
            raise ValueError("window_minutes must be at least 1")

    def _prune(self) -> None:
        cutoff = self.clock() - self._retention_seconds
        self._timestamps = [timestamp for timestamp in self._timestamps if timestamp > cutoff]

    @property
    def _window_seconds(self) -> int:
        return self.window_minutes * 60

    @property
    def _retention_seconds(self) -> int:
        return max(3600, self._window_seconds)

    @property
    def _window_limit(self) -> int:
        return max(1, (self.max_per_hour * self.window_minutes) // 60)

    def _count_since(self, cutoff: float) -> int:
        return sum(1 for timestamp in self._timestamps if timestamp > cutoff)

    def _oldest_since(self, cutoff: float) -> float:
        return next(timestamp for timestamp in self._timestamps if timestamp > cutoff)

    @property
    def remaining(self) -> int:
        """Return available request slots across the hourly cap and smoothing window."""
        self._prune()
        now = self.clock()
        hour_remaining = self.max_per_hour - self._count_since(now - 3600)
        window_remaining = self._window_limit - self._count_since(now - self._window_seconds)
        return max(0, min(hour_remaining, window_remaining))

    async def acquire(self) -> None:
        """Wait until a request slot is available, then consume it."""
        while True:
            now = self.clock()
            self._prune()
            hour_count = self._count_since(now - 3600)
            window_count = self._count_since(now - self._window_seconds)
            if hour_count < self.max_per_hour and window_count < self._window_limit:
                self._timestamps.append(now)
                return

            wait_until = now
            if hour_count >= self.max_per_hour:
                wait_until = max(wait_until, self._oldest_since(now - 3600) + 3600)
            if window_count >= self._window_limit:
                wait_until = max(wait_until, self._oldest_since(now - self._window_seconds) + self._window_seconds)
            wait_seconds = max(0.0, wait_until - now + 1)
            LOG.warning("Rate limit reached, waiting %.0fs", wait_seconds)
            await self.sleeper(wait_seconds)
