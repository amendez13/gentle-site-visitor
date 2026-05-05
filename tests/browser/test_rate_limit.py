"""Tests for the browser rate limiter."""

from __future__ import annotations

import pytest

from gsv.browser.rate_limit import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_blocks_until_oldest_slot_expires() -> None:
    """A saturated limiter sleeps until the sliding window has room."""
    now = 0.0
    sleeps: list[float] = []

    def clock() -> float:
        return now

    async def sleeper(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay

    limiter = RateLimiter(max_per_hour=2, clock=clock, sleeper=sleeper)

    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()

    assert sleeps == [3601.0]
    assert limiter.remaining == 1


def test_rate_limiter_prunes_old_timestamps() -> None:
    """Remaining slots reflect only the current one-hour window."""
    now = 3601.0
    limiter = RateLimiter(max_per_hour=2, clock=lambda: now)
    limiter._timestamps = [0.0, 10.0]

    assert limiter.remaining == 1
    assert limiter._timestamps == [10.0]


@pytest.mark.asyncio
async def test_rate_limiter_scales_shorter_window_without_losing_hourly_cap() -> None:
    """Shorter smoothing windows do not turn the hourly cap into a per-window cap."""
    now = 0.0
    sleeps: list[float] = []

    def clock() -> float:
        return now

    async def sleeper(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay

    limiter = RateLimiter(max_per_hour=2, window_minutes=15, clock=clock, sleeper=sleeper)

    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()

    assert sleeps == [901.0, 2700.0]
    assert now == 3601.0


def test_rate_limiter_rejects_non_positive_limit() -> None:
    """The limiter must have at least one available slot per hour."""
    with pytest.raises(ValueError, match="max_per_hour"):
        RateLimiter(max_per_hour=0)
