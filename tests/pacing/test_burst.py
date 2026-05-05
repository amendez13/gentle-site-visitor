"""Tests for burst cooldown pacing."""

from __future__ import annotations

import random

import pytest

from gsv.pacing import BurstGovernor


@pytest.mark.asyncio
async def test_burst_governor_sleeps_when_interval_is_reached() -> None:
    """A cooldown fires after exactly interval counted actions."""
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    governor = BurstGovernor(interval=5, cooldown_range=(30.0, 90.0), rng=random.Random(3), sleeper=record_sleep)

    assert [await governor.tick() for _ in range(4)] == [0.0, 0.0, 0.0, 0.0]
    cooldown = await governor.tick(boundary="step_burst")

    assert 30.0 <= cooldown <= 90.0
    assert slept == [cooldown]
    assert governor.actions_since_last_cooldown == 0


@pytest.mark.asyncio
async def test_burst_governor_every_n_alias_and_hooks() -> None:
    """The issue-level every_n alias and cooldown hooks are wired."""
    boundaries: list[str] = []
    durations: list[float] = []
    slept: list[float] = []

    async def pre_cooldown(boundary: str) -> None:
        boundaries.append(boundary)

    async def cooldown_sampled(duration: float) -> None:
        durations.append(duration)

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    governor = BurstGovernor(
        every_n=3,
        cooldown_range=(12.0, 12.0),
        rng=random.Random(9),
        on_pre_cooldown=pre_cooldown,
        on_cooldown_sampled=cooldown_sampled,
        sleeper=record_sleep,
    )

    assert await governor.tick(boundary="card_burst") == 0.0
    assert await governor.tick(boundary="card_burst") == 0.0
    assert await governor.tick(boundary="card_burst") == 12.0
    assert boundaries == ["card_burst"]
    assert durations == [12.0]
    assert slept == [12.0]


def test_burst_governor_rejects_invalid_interval() -> None:
    """Intervals must be positive."""
    with pytest.raises(ValueError, match="interval"):
        BurstGovernor(interval=0, cooldown_range=(1.0, 2.0))


def test_burst_governor_requires_interval_and_non_negative_cooldown() -> None:
    """Constructor validation keeps the configured cadence explicit."""
    with pytest.raises(ValueError, match="interval is required"):
        BurstGovernor(cooldown_range=(1.0, 2.0))
    with pytest.raises(ValueError, match="non-negative"):
        BurstGovernor(interval=1, cooldown_range=(-1.0, 2.0))


@pytest.mark.asyncio
async def test_burst_governor_reset_clears_counter() -> None:
    """The visit runner can reset burst state around explicit cooldown steps."""
    governor = BurstGovernor(interval=5, cooldown_range=(1.0, 2.0))

    await governor.tick()
    await governor.tick()
    governor.reset()

    assert governor.actions_since_last_cooldown == 0
