"""Compatibility exports for delay profiles in docs/ARCHITECTURE.md section 4.3."""

from __future__ import annotations

from gsv.config.model import DelayProfileSpec, default_delay_profiles
from gsv.pacing.delay_profile import DelayProfile

__all__ = ["DelayProfile", "DelayProfileSpec", "default_delay_profiles"]
