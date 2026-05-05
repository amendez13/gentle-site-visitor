"""Visit layer API for Gentle Site Visitor."""

from __future__ import annotations

from gsv.visit.context import Cancellation, VisitContext, VisitResult
from gsv.visit.plan import StepOutcome, StepResult, VisitOutcome, VisitPlan, VisitStep
from gsv.visit.runner import VisitRunner
from gsv.visit.sinks import EvidenceSink, JsonlEvidenceSink, NullEvidenceSink
from gsv.visit.steps import (
    Branch,
    BurstCooldown,
    Click,
    Dwell,
    EmptyResult,
    Extract,
    ForEach,
    Navigate,
    RecordEvent,
    Scroll,
    Type,
    WaitFor,
)

__all__ = [
    "Branch",
    "BurstCooldown",
    "Cancellation",
    "Click",
    "Dwell",
    "EmptyResult",
    "EvidenceSink",
    "Extract",
    "ForEach",
    "JsonlEvidenceSink",
    "Navigate",
    "NullEvidenceSink",
    "RecordEvent",
    "Scroll",
    "StepOutcome",
    "StepResult",
    "Type",
    "VisitContext",
    "VisitOutcome",
    "VisitPlan",
    "VisitResult",
    "VisitRunner",
    "VisitStep",
    "WaitFor",
]
