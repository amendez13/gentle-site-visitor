"""Scheduled worker runner."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from random import Random
from typing import Protocol

from gsv.config import VisitorConfig
from gsv.run.exit_codes import EXIT_OK, EXIT_RUNTIME_ERROR
from gsv.schedule.plan import PlannedSlot, compute_daily_plan

LOG = logging.getLogger(__name__)


class Clock(Protocol):
    """Minimal clock protocol for deterministic scheduling tests."""

    def now(self) -> datetime:
        """Return the current local datetime."""


class RunControllerLike(Protocol):
    """Subset of RunController used by the scheduler."""

    async def run_once(self, *, run_id: str | None = None) -> int:
        """Run at most one coordinated run."""


@dataclass(frozen=True)
class SystemClock:
    """Real wall-clock implementation."""

    def now(self) -> datetime:
        """Return local wall-clock time."""
        return datetime.now()


SlotRunFactory = Callable[[PlannedSlot], Awaitable[str | None]]
ControllerFactory = Callable[[], RunControllerLike]
Sleeper = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class SchedulingRunner:
    """Sleep through planned daily slots and execute runs one at a time."""

    config: VisitorConfig
    run_controller_factory: ControllerFactory
    clock: Clock = SystemClock()
    sleeper: Sleeper = asyncio.sleep
    slot_run_factory: SlotRunFactory | None = None

    async def run_today(self, *, target_date: date, rng: Random | None = None) -> int:
        """Execute non-skipped slots for one day and continue after slot failures."""
        plan = compute_daily_plan(self.config.schedule.profiles, self.config.schedule, target_date, rng=rng)
        for slot in plan:
            if slot.skipped:
                LOG.info("Skipping schedule slot %s: %s", slot.profile_id, slot.skip_reason)
                continue
            await self._sleep_until(target_date, slot.scheduled_time)
            try:
                run_id = await self._create_slot_run(slot)
                code = await self.run_controller_factory().run_once(run_id=run_id)
            except Exception:
                LOG.exception("Scheduled slot %s failed before terminal submission", slot.profile_id)
                continue
            if code != EXIT_OK:
                LOG.warning("Scheduled slot %s exited with code %s", slot.profile_id, code)
        return int(EXIT_OK)

    async def run_once(self, *, target_date: date | None = None, rng: Random | None = None) -> int:
        """Execute the next non-skipped slot for one day, then exit."""
        plan_date = target_date or self.clock.now().date()
        plan = compute_daily_plan(self.config.schedule.profiles, self.config.schedule, plan_date, rng=rng)
        for slot in plan:
            if slot.skipped:
                LOG.info("Skipping schedule slot %s: %s", slot.profile_id, slot.skip_reason)
                continue
            scheduled_at = datetime.combine(plan_date, slot.scheduled_time)
            if scheduled_at < self.clock.now():
                continue
            await self._sleep_until(plan_date, slot.scheduled_time)
            try:
                run_id = await self._create_slot_run(slot)
                code = await self.run_controller_factory().run_once(run_id=run_id)
            except Exception:
                LOG.exception("Scheduled slot %s failed before terminal submission", slot.profile_id)
                return int(EXIT_RUNTIME_ERROR)
            if code != EXIT_OK:
                LOG.warning("Scheduled slot %s exited with code %s", slot.profile_id, code)
                return int(code)
            return int(EXIT_OK)
        return int(EXIT_OK)

    async def run_forever(self, *, rng_factory: Callable[[], Random] | None = None) -> int:
        """Recompute the plan each day until interrupted."""
        try:
            while True:
                today = self.clock.now().date()
                rng = rng_factory() if rng_factory is not None else None
                await self.run_today(target_date=today, rng=rng)
                await self._sleep_until(today + timedelta(days=1), time(0, 0))
        except (KeyboardInterrupt, asyncio.CancelledError):
            return int(EXIT_OK)

    async def _sleep_until(self, target_date: date, scheduled_time: time) -> None:
        scheduled_at = datetime.combine(target_date, scheduled_time)
        delay_seconds = max(0.0, (scheduled_at - self.clock.now()).total_seconds())
        await self.sleeper(delay_seconds)

    async def _create_slot_run(self, slot: PlannedSlot) -> str | None:
        if self.slot_run_factory is None:
            return None
        return await self.slot_run_factory(slot)


__all__ = ["Clock", "SchedulingRunner", "SystemClock"]
