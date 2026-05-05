"""Pacing aggregate builder for docs/ARCHITECTURE.md section 4.3."""

from __future__ import annotations

import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from gsv.browser.rate_limit import RateLimiter
from gsv.config.model import SiteConfig, VisitorConfig
from gsv.pacing.burst import BurstGovernor
from gsv.pacing.content_wait import ContentAwareWait
from gsv.pacing.delay_profile import DelayProfile


@dataclass(frozen=True)
class Pacing:
    """Composable pacing dependencies injected into visit execution."""

    delay_profile: DelayProfile
    burst: BurstGovernor
    content_wait: ContentAwareWait
    rate_limiter: RateLimiter


def build_pacing(
    visitor: VisitorConfig,
    site: SiteConfig,
    rate_limiter: RateLimiter,
    *,
    rng: random.Random | None = None,
    on_pre_cooldown: Callable[[str], Awaitable[None]] | None = None,
) -> Pacing:
    """Construct pacing primitives from resolved config and an injected rate limiter."""
    del site
    sampler = rng if rng is not None else random.Random()
    return Pacing(
        delay_profile=DelayProfile.from_registry(visitor.pacing.profile, visitor.pacing.profiles, rng=sampler),
        burst=BurstGovernor(
            interval=visitor.pacing.burst_cooldown_interval,
            cooldown_range=visitor.pacing.burst_cooldown_range,
            rng=sampler,
            on_pre_cooldown=on_pre_cooldown,
        ),
        content_wait=ContentAwareWait(
            timeout_ms=visitor.pacing.content_wait_timeout_ms,
            reaction_range=visitor.pacing.content_wait_reaction_range,
            with_mouse_move=visitor.pacing.content_wait_with_mouse_move,
            rng=sampler,
        ),
        rate_limiter=rate_limiter,
    )
