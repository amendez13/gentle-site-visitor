"""Delay profiles for the pacing layer described in docs/ARCHITECTURE.md section 4.3."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping

from gsv.config.model import DelayProfileSpec


class DelayProfile:
    """Sample and sleep from a named delay profile."""

    def __init__(
        self,
        name: str,
        spec: DelayProfileSpec,
        *,
        rng: random.Random | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.name = name
        self.spec = spec
        self._rng = rng if rng is not None else random.Random()
        self._sleeper = sleeper

    async def sleep(self) -> float:
        """Sleep for one sampled delay and return the duration slept."""
        delay = self.sample()
        if delay == 0.0:
            await self._sleeper(0.0)
            return 0.0
        await self._sleeper(delay)
        return delay

    def sample(self) -> float:
        """Return the next delay sample without sleeping."""
        if self.spec.max_seconds == 0.0 and self.spec.distraction_max_seconds == 0.0:
            return 0.0
        if self._rng.random() < self.spec.distraction_chance:
            return self._rng.uniform(self.spec.distraction_min_seconds, self.spec.distraction_max_seconds)
        return self._rng.uniform(self.spec.min_seconds, self.spec.max_seconds)

    @classmethod
    def from_registry(
        cls,
        name: str,
        registry: Mapping[str, DelayProfileSpec],
        *,
        rng: random.Random | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> "DelayProfile":
        """Build a profile from a registry by name."""
        if name not in registry:
            raise KeyError(f"Unknown delay profile: {name!r}")
        return cls(name, registry[name], rng=rng, sleeper=sleeper)
