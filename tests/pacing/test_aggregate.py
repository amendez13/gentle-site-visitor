"""Tests for pacing aggregate construction."""

from __future__ import annotations

import random

from gsv.browser import RateLimiter
from gsv.config import DelayProfileSpec, PacingConfig, SiteConfig, VisitorConfig
from gsv.pacing import BurstGovernor, ContentAwareWait, DelayProfile, build_pacing


def test_build_pacing_constructs_components_from_config() -> None:
    """The aggregate resolves profile names and preserves the injected limiter."""
    limiter = RateLimiter(max_per_hour=7)
    visitor = VisitorConfig(
        pacing=PacingConfig(
            profile="fast",
            profiles={"fast": DelayProfileSpec(min_seconds=0.0, max_seconds=0.0)},
            burst_cooldown_interval=2,
            burst_cooldown_range=(3.0, 4.0),
            content_wait_timeout_ms=250,
            content_wait_reaction_range=(0.0, 0.0),
            content_wait_with_mouse_move=False,
        )
    )

    pacing = build_pacing(visitor, SiteConfig(name="example"), limiter, rng=random.Random(1))

    assert isinstance(pacing.delay_profile, DelayProfile)
    assert pacing.delay_profile.name == "fast"
    assert isinstance(pacing.burst, BurstGovernor)
    assert isinstance(pacing.content_wait, ContentAwareWait)
    assert pacing.rate_limiter is limiter
