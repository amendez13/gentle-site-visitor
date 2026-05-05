"""Visit execution context for docs/ARCHITECTURE.md section 4.4."""

from __future__ import annotations

import random
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any, Protocol

from gsv.config import SiteConfig, VisitorConfig
from gsv.pacing import Pacing
from gsv.session import SiteAuthAdapter
from gsv.visit.plan import StepResult, VisitOutcome
from gsv.visit.sinks import EvidenceSink, NullEvidenceSink


class Cancellation(Protocol):
    """Cancellation seam that S7 plugs into the visit runner."""

    def check(self, *, force: bool = False, boundary: str = "") -> Awaitable[None]:
        """Check for cancellation at a named boundary."""


@dataclass
class VisitContext:
    """Runtime dependencies shared by visit steps."""

    page: Any
    pacing: Pacing
    config: VisitorConfig = field(default_factory=VisitorConfig)
    site: SiteConfig = field(default_factory=lambda: SiteConfig(name="default"))
    session: Any | None = None
    site_adapter: SiteAuthAdapter | None = None
    rng: random.Random = field(default_factory=random.Random)
    sink: EvidenceSink = field(default_factory=NullEvidenceSink)
    cancellation: Cancellation | None = None
    extracted: dict[str, Any] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)

    def increment(self, name: str, amount: int = 1) -> None:
        """Increment a framework-level counter."""
        self.counters[name] = self.counters.get(name, 0) + amount


@dataclass
class VisitResult:
    """Result of running a visit plan."""

    outcome: VisitOutcome
    error: str | None
    counters: dict[str, int]
    extracted: dict[str, Any]
    step_results: list[StepResult]
