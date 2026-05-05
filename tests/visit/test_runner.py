"""Tests for VisitRunner wrapping behavior."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from gsv.observability import BrowserMeta, RunRef, SessionManifest, SessionRecorder
from gsv.visit import StepResult, VisitContext, VisitPlan, VisitRunner
from tests.visit.conftest import FakePacing


@dataclass
class RecordingStep:
    """Step that records execution into a shared event list."""

    events: list[str]
    name: str = "step"
    content_marker: str | None = "#ready"
    fail: bool = False

    async def execute(self, _ctx: VisitContext) -> StepResult:
        self.events.append("execute")
        if self.fail:
            raise RuntimeError("step exploded")
        return StepResult(name=self.name, outcome="ok")


class RecordingCancellation:
    """Cancellation seam test double."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.boundaries: list[str] = []

    async def check(self, *, force: bool = False, boundary: str = "") -> None:
        del force
        self.boundaries.append(boundary)
        self.events.append(f"cancel:{boundary}")


@pytest.mark.asyncio
async def test_runner_applies_seven_stage_wrap_in_order(fake_page) -> None:  # type: ignore[no-untyped-def]
    """Every step is wrapped in the canonical order."""
    events: list[str] = []
    cancellation = RecordingCancellation(events)
    ctx = VisitContext(
        page=fake_page,
        pacing=FakePacing(events),  # type: ignore[arg-type]
        cancellation=cancellation,
    )

    result = await VisitRunner(ctx).run(VisitPlan([RecordingStep(events)]))

    assert result.outcome == "completed"
    assert events == [
        "cancel:step_pre",
        "rate_limit",
        "execute",
        "content_wait",
        "delay",
        "burst",
        "cancel:step_post",
    ]
    assert cancellation.boundaries == ["step_pre", "step_post"]
    assert result.counters["requests_made"] == 1
    assert result.counters["cancellation_checks_visited"] == 2


@pytest.mark.asyncio
async def test_runner_records_step_failure_and_still_runs_post_wrap(fake_page) -> None:  # type: ignore[no-untyped-def]
    """Step exceptions become failure results and still receive post-execute pacing."""
    events: list[str] = []
    ctx = VisitContext(page=fake_page, pacing=FakePacing(events, cooldown=10.0))  # type: ignore[arg-type]

    result = await VisitRunner(ctx).run(VisitPlan([RecordingStep(events, fail=True)]))

    assert result.outcome == "failed"
    assert result.error == "step exploded"
    assert result.step_results[0].outcome == "fail"
    assert events == ["rate_limit", "execute", "content_wait", "delay", "burst"]
    assert result.counters["requests_made"] == 1
    assert result.counters["cooldowns"] == 1


@pytest.mark.asyncio
async def test_runner_uses_custom_outcome_classifier(fake_page) -> None:  # type: ignore[no-untyped-def]
    """Plans can classify successful step runs as blocked."""
    ctx = VisitContext(page=fake_page, pacing=FakePacing())  # type: ignore[arg-type]

    result = await VisitRunner(ctx).run(VisitPlan([RecordingStep([])], outcome_classifier=lambda _results: "blocked"))

    assert result.outcome == "blocked"


@pytest.mark.asyncio
async def test_runner_reports_cancellation_from_boundary(fake_page) -> None:  # type: ignore[no-untyped-def]
    """Cancellation seam exceptions produce a cancelled VisitResult."""

    class RunCancellationRequested(RuntimeError):
        pass

    class CancelsImmediately:
        async def check(self, *, force: bool = False, boundary: str = "") -> None:
            del force, boundary
            raise RunCancellationRequested("stop")

    ctx = VisitContext(
        page=fake_page,
        pacing=FakePacing(),  # type: ignore[arg-type]
        cancellation=CancelsImmediately(),
    )

    result = await VisitRunner(ctx).run(VisitPlan([RecordingStep([])]))

    assert result.outcome == "cancelled"
    assert result.error == "stop"
    assert result.step_results == []


@pytest.mark.asyncio
async def test_runner_finalizes_attached_recorder(fake_page, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Top-level VisitRunner writes framework counters into the session manifest."""
    recorder = SessionRecorder.open(
        sessions_dir=tmp_path,
        mode="always",
        run=RunRef(id="r1", plan_name="plan"),
        browser_meta_provider=BrowserMeta,
    )
    assert recorder is not None
    ctx = VisitContext(
        page=fake_page,
        pacing=FakePacing(),  # type: ignore[arg-type]
        recorder=recorder,
    )

    result = await VisitRunner(ctx).run(VisitPlan([RecordingStep([])]))

    manifest = SessionManifest.from_json((recorder.session_dir / "manifest.json").read_text(encoding="utf-8"))
    assert result.outcome == "completed"
    assert manifest.outcome == "completed"
    assert manifest.counters == {"requests_made": 1}
