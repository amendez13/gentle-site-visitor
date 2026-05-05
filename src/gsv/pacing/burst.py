"""Burst cooldown governor for the pacing layer described in docs/ARCHITECTURE.md section 4.3."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable


class BurstGovernor:
    """Sleep for a cooldown after a configured number of actions."""

    def __init__(
        self,
        *,
        interval: int | None = None,
        every_n: int | None = None,
        cooldown_range: tuple[float, float],
        rng: random.Random | None = None,
        on_pre_cooldown: Callable[[str], Awaitable[None]] | None = None,
        on_cooldown_sampled: Callable[[float], Awaitable[None]] | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        resolved_interval = interval if interval is not None else every_n
        if resolved_interval is None:
            raise ValueError("interval is required")
        if resolved_interval < 1:
            raise ValueError("interval must be at least 1")
        if cooldown_range[0] < 0 or cooldown_range[1] < 0:
            raise ValueError("cooldown_range values must be non-negative")
        self._interval = resolved_interval
        self._cooldown_range = (min(cooldown_range), max(cooldown_range))
        self._rng = rng if rng is not None else random.Random()
        self._on_pre_cooldown = on_pre_cooldown
        self._on_cooldown_sampled = on_cooldown_sampled
        self._sleeper = sleeper
        self._actions_since_last_cooldown = 0

    @property
    def actions_since_last_cooldown(self) -> int:
        """Return the number of actions counted since the last cooldown."""
        return self._actions_since_last_cooldown

    async def tick(self, *, boundary: str = "burst") -> float:
        """Count one action, sleep if the interval is reached, and return slept seconds."""
        self._actions_since_last_cooldown += 1
        if self._actions_since_last_cooldown < self._interval:
            return 0.0

        duration = self._rng.uniform(*self._cooldown_range)
        if self._on_pre_cooldown is not None:
            await self._on_pre_cooldown(boundary)
        if self._on_cooldown_sampled is not None:
            await self._on_cooldown_sampled(duration)
        await self._sleeper(duration)
        self._actions_since_last_cooldown = 0
        return duration

    def reset(self) -> None:
        """Reset the current burst counter without sleeping."""
        self._actions_since_last_cooldown = 0
