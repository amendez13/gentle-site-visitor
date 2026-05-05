"""Typed schedule profile rows loaded from YAML."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduleProfile:
    """One macro-scheduling profile for a site visit run."""

    id: int | str
    name: str
    enabled: bool = True
    frequency: str = "daily"
    preferred_time: str = "09:00"
    jitter_minutes: int = 30


__all__ = ["ScheduleProfile"]
