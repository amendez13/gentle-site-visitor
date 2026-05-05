"""Pacing layer API for Gentle Site Visitor."""

from __future__ import annotations

from gsv.config.model import DelayProfileSpec, default_delay_profiles
from gsv.pacing.aggregate import Pacing, build_pacing
from gsv.pacing.burst import BurstGovernor
from gsv.pacing.content_wait import ContentAwareWait
from gsv.pacing.delay_profile import DelayProfile

__all__ = [
    "BurstGovernor",
    "ContentAwareWait",
    "DelayProfile",
    "DelayProfileSpec",
    "Pacing",
    "build_pacing",
    "default_delay_profiles",
]
