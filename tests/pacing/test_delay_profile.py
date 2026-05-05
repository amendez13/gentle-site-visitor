"""Tests for named pacing delay profiles."""

from __future__ import annotations

import random

import pytest

from gsv.config import DelayProfileSpec, default_delay_profiles
from gsv.pacing import DelayProfile
from gsv.pacing.profiles import DelayProfile as ProfilesDelayProfile
from gsv.pacing.profiles import DelayProfileSpec as ProfilesDelayProfileSpec
from gsv.pacing.profiles import default_delay_profiles as profiles_default_delay_profiles


async def noop_sleep(_seconds: float) -> None:
    """Avoid real wall-clock sleeps in profile tests."""
    return None


def test_production_profile_distribution_with_seeded_rng() -> None:
    """The production profile keeps CE's mostly-short, occasional-long shape."""
    profile = DelayProfile.from_registry("production", default_delay_profiles(), rng=random.Random(42))

    samples = [profile.sample() for _ in range(1000)]
    distraction_count = sum(1 for sample in samples if 15.0 <= sample <= 45.0)

    assert 70 <= distraction_count <= 130
    assert all(2.0 <= sample <= 5.0 or 15.0 <= sample <= 45.0 for sample in samples)
    assert 5.0 <= sum(samples) / len(samples) <= 8.0


@pytest.mark.asyncio
async def test_disabled_profile_yields_zero_delay() -> None:
    """The disabled profile yields the loop but returns zero delay."""
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    profile = DelayProfile.from_registry("disabled", default_delay_profiles(), rng=random.Random(1), sleeper=record_sleep)

    assert await profile.sleep() == 0.0
    assert slept == [0.0]


def test_registry_lookup_rejects_unknown_profile() -> None:
    """Profile names must resolve against the configured registry."""
    with pytest.raises(KeyError, match="Unknown delay profile"):
        DelayProfile.from_registry("missing", default_delay_profiles())


def test_profiles_module_reexports_profile_api() -> None:
    """The issue-level profiles module stays as a stable import path."""
    assert ProfilesDelayProfile is DelayProfile
    assert ProfilesDelayProfileSpec is DelayProfileSpec
    assert "production" in profiles_default_delay_profiles()


@pytest.mark.asyncio
async def test_custom_profile_registers_and_resolves() -> None:
    """App-defined profiles can be added to the registry."""
    registry = default_delay_profiles()
    registry["fast"] = DelayProfileSpec(min_seconds=1.25, max_seconds=1.25)
    profile = DelayProfile.from_registry("fast", registry, rng=random.Random(1), sleeper=noop_sleep)

    assert await profile.sleep() == 1.25
