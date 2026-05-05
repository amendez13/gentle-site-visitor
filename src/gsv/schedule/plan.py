"""Pure planning logic for daily Gentle Site Visitor execution windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from random import Random
from typing import Any, Mapping

_DAY_ABBREVIATIONS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class PlannedSlot:
    profile_id: int | str
    profile_name: str
    scheduled_time: time
    original_time: time
    skipped: bool = False
    skip_reason: str | None = None


def _parse_hhmm(value: str | time, *, field_name: str) -> time:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)

    raw = str(value).strip()
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError(f"{field_name} must be in HH:MM format")
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"{field_name} must be in HH:MM format") from exc

    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError(f"{field_name} must be in HH:MM format")
    return time(hour=hours, minute=minutes)


def _time_to_minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _minutes_to_time(value: int) -> time:
    clamped = max(0, min(23 * 60 + 59, value))
    return time(hour=clamped // 60, minute=clamped % 60)


def _coerce_int(value: Any, *, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _get_field(record: Mapping[str, Any] | Any, field_name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(field_name, default)
    return getattr(record, field_name, default)


def matches_day(frequency: str, target_date: date) -> bool:
    """Return whether the given frequency includes the target day."""

    clean_frequency = str(frequency or "").strip().lower()
    if clean_frequency == "daily":
        return True
    if clean_frequency == "weekdays":
        return target_date.weekday() < 5
    if clean_frequency == "weekends":
        return target_date.weekday() >= 5

    if not clean_frequency:
        raise ValueError("frequency must be non-empty")

    parts = [part.strip() for part in clean_frequency.split(",") if part.strip()]
    if not parts:
        raise ValueError("frequency must be non-empty")

    for part in parts:
        if part not in _DAY_ABBREVIATIONS:
            raise ValueError("frequency must be daily, weekdays, weekends, or comma-separated day abbreviations")

    return _DAY_ABBREVIATIONS[target_date.weekday()] in set(parts)


def compute_jittered_time(preferred_time: time, jitter_minutes: int, rng: Random) -> time:
    """Apply +/- jitter to preferred_time while keeping result within the same day."""

    jitter = _coerce_int(jitter_minutes, field_name="jitter_minutes")
    if jitter < 0:
        raise ValueError("jitter_minutes must be non-negative")

    preferred_minutes = _time_to_minutes(preferred_time)
    if jitter == 0:
        return _minutes_to_time(preferred_minutes)

    offset = rng.randint(-jitter, jitter)
    return _minutes_to_time(preferred_minutes + offset)


def clamp_to_window(value: time, window_start: time, window_end: time) -> tuple[time, bool]:
    """Clamp a time to the inclusive activity window."""

    value_minutes = _time_to_minutes(value)
    start_minutes = _time_to_minutes(window_start)
    end_minutes = _time_to_minutes(window_end)

    if value_minutes < start_minutes:
        return window_start, True
    if value_minutes > end_minutes:
        return window_end, True
    return value, False


def enforce_rest_periods(
    slots: list[PlannedSlot],
    rest_min: int,
    rest_max: int,
    window_end: time,
    rng: Random,
) -> list[PlannedSlot]:
    """Push slots forward when they violate randomized rest gaps."""

    min_gap = _coerce_int(rest_min, field_name="rest_min")
    max_gap = _coerce_int(rest_max, field_name="rest_max")
    if min_gap < 0 or max_gap < 0:
        raise ValueError("rest periods must be non-negative")
    if min_gap > max_gap:
        raise ValueError("rest_min must be less than or equal to rest_max")

    end_minutes = _time_to_minutes(window_end)
    ordered = sorted(slots, key=lambda slot: _time_to_minutes(slot.scheduled_time))

    last_kept_minutes: int | None = None
    for slot in ordered:
        candidate_minutes = _time_to_minutes(slot.scheduled_time)

        if last_kept_minutes is not None:
            required_gap = rng.randint(min_gap, max_gap)
            earliest_allowed = last_kept_minutes + required_gap
            if candidate_minutes < earliest_allowed:
                candidate_minutes = earliest_allowed

        if candidate_minutes > end_minutes:
            slot.scheduled_time = window_end
            slot.skipped = True
            slot.skip_reason = "outside_activity_window"
            continue

        slot.scheduled_time = _minutes_to_time(candidate_minutes)
        slot.skipped = False
        slot.skip_reason = None
        last_kept_minutes = candidate_minutes

    return ordered


def compute_daily_plan(
    profiles: list[Mapping[str, Any] | Any],
    config: Mapping[str, Any] | Any,
    target_date: date,
    *,
    rng: Random | None = None,
) -> list[PlannedSlot]:
    """Compute a sorted daily plan with jitter and rest-period enforcement."""

    plan_rng = rng or Random()

    window_start = _parse_hhmm(
        _get_field(config, "activity_window_start", "08:00"),
        field_name="activity_window_start",
    )
    window_end = _parse_hhmm(
        _get_field(config, "activity_window_end", "23:00"),
        field_name="activity_window_end",
    )
    if _time_to_minutes(window_start) > _time_to_minutes(window_end):
        raise ValueError("activity window must not cross midnight")

    rest_min = _coerce_int(_get_field(config, "rest_min_minutes", 30), field_name="rest_min_minutes")
    rest_max = _coerce_int(_get_field(config, "rest_max_minutes", 90), field_name="rest_max_minutes")

    candidate_slots: list[PlannedSlot] = []
    for profile in profiles:
        enabled = bool(_get_field(profile, "enabled", True))
        if not enabled:
            continue

        frequency = str(_get_field(profile, "frequency", "daily") or "daily")
        if not matches_day(frequency, target_date):
            continue

        preferred = _parse_hhmm(_get_field(profile, "preferred_time", "09:00"), field_name="preferred_time")
        jitter_minutes = _coerce_int(_get_field(profile, "jitter_minutes", 30), field_name="jitter_minutes")
        jittered = compute_jittered_time(preferred, jitter_minutes, plan_rng)
        scheduled, _ = clamp_to_window(jittered, window_start, window_end)
        profile_id = _get_field(profile, "id")

        candidate_slots.append(
            PlannedSlot(
                profile_id=profile_id if isinstance(profile_id, str) else _coerce_int(profile_id, field_name="profile_id"),
                profile_name=str(_get_field(profile, "name", "")).strip() or f"profile-{profile_id}",
                scheduled_time=scheduled,
                original_time=preferred,
            )
        )

    if not candidate_slots:
        return []

    return enforce_rest_periods(candidate_slots, rest_min, rest_max, window_end, plan_rng)
