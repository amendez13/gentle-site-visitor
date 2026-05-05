"""Tests for scheduled worker execution."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, datetime, time
from typing import Any

from gsv.config import ScheduleConfig, VisitorConfig
from gsv.schedule import ScheduleProfile
from gsv.schedule.runner import SchedulingRunner


class FakeClock:
    """Clock with a fixed current instant."""

    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


class FakeController:
    """Controller double that records run ids."""

    def __init__(self, seen: list[str | None], code: int = 0) -> None:
        self.seen = seen
        self.code = code

    async def run_once(self, *, run_id: str | None = None) -> int:
        self.seen.append(run_id)
        return self.code


async def test_scheduling_runner_sleeps_creates_run_and_executes_slots() -> None:
    """Scheduled mode waits until each slot and executes created run ids sequentially."""
    visitor = replace(
        VisitorConfig(),
        schedule=ScheduleConfig(
            activity_window_start="08:00",
            activity_window_end="12:00",
            rest_min_minutes=30,
            rest_max_minutes=30,
            profiles=[
                ScheduleProfile(id="morning", name="Morning", preferred_time="09:00", jitter_minutes=0),
                ScheduleProfile(id="midday", name="Midday", preferred_time="09:10", jitter_minutes=0),
            ],
        ),
    )
    sleeps: list[float] = []
    created: list[str] = []
    seen: list[str | None] = []

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    async def create_run(slot: Any) -> str:
        created.append(str(slot.profile_id))
        return f"run-{slot.profile_id}"

    runner = SchedulingRunner(
        config=visitor,
        clock=FakeClock(datetime(2026, 5, 4, 8, 45)),
        sleeper=sleeper,
        slot_run_factory=create_run,
        run_controller_factory=lambda: FakeController(seen),
    )

    code = await runner.run_today(target_date=date(2026, 5, 4))

    assert code == 0
    assert sleeps == [15 * 60, 45 * 60]
    assert created == ["morning", "midday"]
    assert seen == ["run-morning", "run-midday"]


async def test_scheduling_runner_continues_after_slot_failure() -> None:
    """A non-zero slot exit is logged but does not kill the day's remaining slots."""
    visitor = replace(
        VisitorConfig(),
        schedule=ScheduleConfig(
            rest_min_minutes=30,
            rest_max_minutes=30,
            profiles=[
                ScheduleProfile(id=1, name="One", preferred_time="09:00", jitter_minutes=0),
                ScheduleProfile(id=2, name="Two", preferred_time="10:00", jitter_minutes=0),
            ],
        ),
    )
    calls: list[str | None] = []
    codes = [1, 0]

    def controller_factory() -> FakeController:
        return FakeController(calls, code=codes.pop(0))

    runner = SchedulingRunner(
        config=visitor,
        clock=FakeClock(datetime(2026, 5, 4, 12, 0)),
        sleeper=lambda delay: asyncio.sleep(0),
        run_controller_factory=controller_factory,
    )

    code = await runner.run_today(target_date=date(2026, 5, 4))

    assert code == 0
    assert calls == [None, None]


async def test_scheduling_runner_continues_after_slot_exception() -> None:
    """An exception in one scheduled slot does not prevent later slots."""
    visitor = replace(
        VisitorConfig(),
        schedule=ScheduleConfig(
            rest_min_minutes=30,
            rest_max_minutes=30,
            profiles=[
                ScheduleProfile(id=1, name="One", preferred_time="09:00", jitter_minutes=0),
                ScheduleProfile(id=2, name="Two", preferred_time="10:00", jitter_minutes=0),
            ],
        ),
    )
    calls: list[str | None] = []
    fail_first = True

    async def create_run(slot: Any) -> str:
        nonlocal fail_first
        if fail_first:
            fail_first = False
            raise RuntimeError("create failed")
        return f"run-{slot.profile_id}"

    runner = SchedulingRunner(
        config=visitor,
        clock=FakeClock(datetime(2026, 5, 4, 12, 0)),
        sleeper=lambda delay: asyncio.sleep(0),
        slot_run_factory=create_run,
        run_controller_factory=lambda: FakeController(calls),
    )

    code = await runner.run_today(target_date=date(2026, 5, 4))

    assert code == 0
    assert calls == ["run-2"]


async def test_scheduling_runner_run_once_executes_only_next_future_slot() -> None:
    """One-shot scheduled mode executes at most one upcoming slot."""
    visitor = replace(
        VisitorConfig(),
        schedule=ScheduleConfig(
            rest_min_minutes=30,
            rest_max_minutes=30,
            profiles=[
                ScheduleProfile(id=1, name="One", preferred_time="09:00", jitter_minutes=0),
                ScheduleProfile(id=2, name="Two", preferred_time="10:00", jitter_minutes=0),
                ScheduleProfile(id=3, name="Three", preferred_time="11:00", jitter_minutes=0),
            ],
        ),
    )
    sleeps: list[float] = []
    calls: list[str | None] = []

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    async def create_run(slot: Any) -> str:
        return f"run-{slot.profile_id}"

    runner = SchedulingRunner(
        config=visitor,
        clock=FakeClock(datetime(2026, 5, 4, 9, 5)),
        sleeper=sleeper,
        slot_run_factory=create_run,
        run_controller_factory=lambda: FakeController(calls),
    )

    code = await runner.run_once(target_date=date(2026, 5, 4))

    assert code == 0
    assert sleeps == [55 * 60]
    assert calls == ["run-2"]


async def test_scheduling_runner_run_once_uses_clock_date_by_default() -> None:
    """One-shot scheduled mode uses the scheduler's local clock date."""
    seen_dates: list[date] = []
    visitor = replace(
        VisitorConfig(),
        schedule=ScheduleConfig(
            profiles=[ScheduleProfile(id=1, name="One", preferred_time="23:30", jitter_minutes=0)],
        ),
    )

    async def sleeper(delay: float) -> None:
        del delay

    runner = SchedulingRunner(
        config=visitor,
        clock=FakeClock(datetime(2026, 5, 4, 23, 0)),
        sleeper=sleeper,
        run_controller_factory=lambda: FakeController([]),
    )

    original_sleep_until = runner._sleep_until

    async def record_date(target_date: date, scheduled_time: time) -> None:
        seen_dates.append(target_date)
        await original_sleep_until(target_date, scheduled_time)

    object.__setattr__(runner, "_sleep_until", record_date)

    assert await runner.run_once() == 0
    assert seen_dates == [date(2026, 5, 4)]


async def test_scheduling_runner_run_once_surfaces_slot_failure() -> None:
    """One-shot scheduled mode returns the first non-zero slot exit code."""
    visitor = replace(
        VisitorConfig(),
        schedule=ScheduleConfig(
            profiles=[ScheduleProfile(id=1, name="One", preferred_time="09:00", jitter_minutes=0)],
        ),
    )
    calls: list[str | None] = []

    runner = SchedulingRunner(
        config=visitor,
        clock=FakeClock(datetime(2026, 5, 4, 8, 0)),
        sleeper=lambda delay: asyncio.sleep(0),
        run_controller_factory=lambda: FakeController(calls, code=1),
    )

    assert await runner.run_once(target_date=date(2026, 5, 4)) == 1
    assert calls == [None]


async def test_scheduling_runner_skips_overflow_slots() -> None:
    """Skipped planner slots are not created or executed."""
    visitor = replace(
        VisitorConfig(),
        schedule=ScheduleConfig(
            activity_window_start="09:00",
            activity_window_end="09:30",
            rest_min_minutes=30,
            rest_max_minutes=30,
            profiles=[
                ScheduleProfile(id=1, name="One", preferred_time="09:00", jitter_minutes=0),
                ScheduleProfile(id=2, name="Two", preferred_time="09:05", jitter_minutes=0),
                ScheduleProfile(id=3, name="Three", preferred_time="09:10", jitter_minutes=0),
            ],
        ),
    )
    calls: list[str | None] = []

    runner = SchedulingRunner(
        config=visitor,
        clock=FakeClock(datetime(2026, 5, 4, 12, 0)),
        sleeper=lambda delay: asyncio.sleep(0),
        run_controller_factory=lambda: FakeController(calls),
    )

    code = await runner.run_today(target_date=date(2026, 5, 4))

    assert code == 0
    assert calls == [None, None]


async def test_scheduling_runner_run_forever_honors_cancelled_error() -> None:
    """Ctrl-C between slots is represented as CancelledError and exits cleanly."""
    visitor = replace(VisitorConfig(), schedule=ScheduleConfig())

    async def sleeper(delay: float) -> None:
        del delay
        raise asyncio.CancelledError

    runner = SchedulingRunner(
        config=visitor,
        clock=FakeClock(datetime(2026, 5, 4, 23, 59)),
        sleeper=sleeper,
        run_controller_factory=lambda: FakeController([]),
    )

    assert await runner.run_forever() == 0
