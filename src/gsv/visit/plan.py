"""Visit plan contracts for docs/ARCHITECTURE.md section 4.4."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from gsv.visit.context import VisitContext

StepOutcome = Literal["ok", "fail", "skip"]
VisitOutcome = Literal["completed", "failed", "cancelled", "blocked"]


@dataclass
class StepResult:
    """Result emitted by a single visit step."""

    name: str
    outcome: StepOutcome
    error: str | None = None
    extracted: Any = None
    duration_seconds: float = 0.0


class VisitStep(Protocol):
    """Executable step protocol wrapped by the visit runner."""

    name: str
    content_marker: str | None

    async def execute(self, ctx: VisitContext) -> StepResult:
        """Run this step against a visit context."""


OutcomeClassifier = Callable[[list[StepResult]], VisitOutcome]


@dataclass
class VisitPlan:
    """A declarative list of visit steps plus optional outcome classification."""

    steps: list[VisitStep | "VisitPlan"] = field(default_factory=list)
    outcome_classifier: OutcomeClassifier | None = None

    def classify(self, step_results: list[StepResult]) -> VisitOutcome:
        """Classify the completed step list into a run outcome."""
        if self.outcome_classifier is not None:
            return self.outcome_classifier(step_results)
        if any(result.outcome == "fail" for result in step_results):
            return "failed"
        return "completed"
