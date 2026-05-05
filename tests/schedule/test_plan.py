"""Tests for the S8 pure schedule planner."""

from __future__ import annotations

from datetime import date, time
from random import Random

import pytest

from gsv.schedule import (
    PlannedSlot,
    clamp_to_window,
    compute_daily_plan,
    compute_jittered_time,
    enforce_rest_periods,
    matches_day,
)
from gsv.schedule.plan import _parse_hhmm


def _profile(
    profile_id: int | str,
    *,
    name: str = "profile",
    frequency: str = "daily",
    preferred_time: str = "09:00",
    jitter_minutes: int = 0,
    enabled: bool = True,
) -> dict[str, object]:
    return {
        "id": profile_id,
        "name": f"{name}-{profile_id}",
        "enabled": enabled,
        "frequency": frequency,
        "preferred_time": preferred_time,
        "jitter_minutes": jitter_minutes,
    }


def _config(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "activity_window_start": "08:00",
        "activity_window_end": "23:00",
        "rest_min_minutes": 30,
        "rest_max_minutes": 90,
    }
    base.update(overrides)
    return base


class TestMatchesDay:
    def test_daily_matches_every_day(self) -> None:
        monday = date(2026, 4, 6)
        for offset in range(7):
            assert matches_day("daily", monday.fromordinal(monday.toordinal() + offset))

    def test_weekdays_match_only_mon_to_fri(self) -> None:
        assert matches_day("weekdays", date(2026, 4, 6))
        assert matches_day("weekdays", date(2026, 4, 10))
        assert not matches_day("weekdays", date(2026, 4, 11))
        assert not matches_day("weekdays", date(2026, 4, 12))

    def test_weekends_match_only_sat_to_sun(self) -> None:
        assert not matches_day("weekends", date(2026, 4, 10))
        assert matches_day("weekends", date(2026, 4, 11))
        assert matches_day("weekends", date(2026, 4, 12))

    def test_custom_days_match_specific_days(self) -> None:
        assert matches_day("mon,wed,fri", date(2026, 4, 6))
        assert not matches_day("mon,wed,fri", date(2026, 4, 7))
        assert matches_day("mon,wed,fri", date(2026, 4, 8))

    def test_invalid_frequency_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="frequency"):
            matches_day("monday", date(2026, 4, 6))

    def test_empty_frequency_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            matches_day("", date(2026, 4, 6))
        with pytest.raises(ValueError, match="non-empty"):
            matches_day(",", date(2026, 4, 6))


class TestParseHHMM:
    def test_time_value_is_normalized(self) -> None:
        assert _parse_hhmm(time(9, 30, 45), field_name="field") == time(9, 30)

    @pytest.mark.parametrize("value", ["9", "aa:00", "24:00"])
    def test_invalid_values_raise(self, value: str) -> None:
        with pytest.raises(ValueError, match="HH:MM"):
            _parse_hhmm(value, field_name="field")


class TestComputeJitteredTime:
    def test_zero_jitter_returns_preferred_time(self) -> None:
        preferred = time(9, 30)
        assert compute_jittered_time(preferred, 0, Random(1)) == preferred

    def test_jitter_stays_within_range(self) -> None:
        preferred = time(10, 0)
        rng = Random(7)
        for _ in range(50):
            actual = compute_jittered_time(preferred, 30, rng)
            delta = abs((actual.hour * 60 + actual.minute) - (preferred.hour * 60 + preferred.minute))
            assert delta <= 30

    def test_seeded_rng_is_deterministic(self) -> None:
        preferred = time(14, 0)
        first = compute_jittered_time(preferred, 45, Random(99))
        second = compute_jittered_time(preferred, 45, Random(99))
        assert first == second

    def test_jitter_never_returns_time_before_midnight(self) -> None:
        preferred = time(0, 5)
        actual = compute_jittered_time(preferred, 30, Random(1))
        assert actual >= time(0, 0)

    def test_jitter_never_returns_time_after_end_of_day(self) -> None:
        preferred = time(23, 55)
        actual = compute_jittered_time(preferred, 30, Random(2))
        assert actual <= time(23, 59)

    def test_negative_jitter_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            compute_jittered_time(time(9, 0), -1, Random(1))


class TestClampToWindow:
    def test_before_window_start_is_clamped(self) -> None:
        clamped, changed = clamp_to_window(time(7, 30), time(8, 0), time(23, 0))
        assert changed
        assert clamped == time(8, 0)

    def test_after_window_end_is_clamped(self) -> None:
        clamped, changed = clamp_to_window(time(23, 30), time(8, 0), time(23, 0))
        assert changed
        assert clamped == time(23, 0)

    def test_time_inside_window_is_unchanged(self) -> None:
        clamped, changed = clamp_to_window(time(10, 0), time(8, 0), time(23, 0))
        assert not changed
        assert clamped == time(10, 0)


class TestEnforceRestPeriods:
    def test_two_close_slots_pushes_second_forward(self) -> None:
        slots = [
            PlannedSlot(profile_id=1, profile_name="a", scheduled_time=time(9, 0), original_time=time(9, 0)),
            PlannedSlot(profile_id=2, profile_name="b", scheduled_time=time(9, 10), original_time=time(9, 10)),
        ]
        plan = enforce_rest_periods(slots, rest_min=30, rest_max=30, window_end=time(23, 0), rng=Random(1))
        assert [slot.scheduled_time for slot in plan] == [time(9, 0), time(9, 30)]

    def test_three_clustered_slots_cascade_forward(self) -> None:
        slots = [
            PlannedSlot(profile_id=1, profile_name="a", scheduled_time=time(9, 0), original_time=time(9, 0)),
            PlannedSlot(profile_id=2, profile_name="b", scheduled_time=time(9, 5), original_time=time(9, 5)),
            PlannedSlot(profile_id=3, profile_name="c", scheduled_time=time(9, 10), original_time=time(9, 10)),
        ]
        plan = enforce_rest_periods(slots, rest_min=30, rest_max=30, window_end=time(23, 0), rng=Random(3))
        assert [slot.scheduled_time for slot in plan] == [time(9, 0), time(9, 30), time(10, 0)]

    def test_slot_pushed_past_window_end_is_marked_skipped(self) -> None:
        slots = [
            PlannedSlot(profile_id=1, profile_name="a", scheduled_time=time(22, 50), original_time=time(22, 50)),
            PlannedSlot(profile_id=2, profile_name="b", scheduled_time=time(22, 55), original_time=time(22, 55)),
        ]
        plan = enforce_rest_periods(slots, rest_min=20, rest_max=20, window_end=time(23, 0), rng=Random(1))

        assert plan[0].skipped is False
        assert plan[1].scheduled_time == time(23, 0)
        assert plan[1].skipped is True
        assert plan[1].skip_reason == "outside_activity_window"

    @pytest.mark.parametrize(("rest_min", "rest_max", "message"), [(-1, 30, "non-negative"), (60, 30, "less than")])
    def test_invalid_rest_periods_raise(self, rest_min: int, rest_max: int, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            enforce_rest_periods([], rest_min=rest_min, rest_max=rest_max, window_end=time(23, 0), rng=Random(1))


class TestComputeDailyPlan:
    def test_empty_profiles_returns_empty_plan(self) -> None:
        assert compute_daily_plan([], _config(), date(2026, 4, 6), rng=Random(1)) == []

    def test_all_profiles_filtered_by_frequency_returns_empty_plan(self) -> None:
        profiles = [_profile(1, frequency="weekdays")]
        plan = compute_daily_plan(profiles, _config(), date(2026, 4, 11), rng=Random(1))
        assert plan == []

    def test_normal_plan_is_sorted_and_rest_enforced(self) -> None:
        profiles = [
            _profile(1, preferred_time="09:00", jitter_minutes=0),
            _profile(2, preferred_time="09:15", jitter_minutes=0),
            _profile(3, preferred_time="10:00", jitter_minutes=0),
        ]
        config = _config(rest_min_minutes=30, rest_max_minutes=30)
        plan = compute_daily_plan(profiles, config, date(2026, 4, 7), rng=Random(5))

        assert [slot.profile_id for slot in plan] == [1, 2, 3]
        assert [slot.scheduled_time for slot in plan] == [time(9, 0), time(9, 30), time(10, 0)]
        assert all(not slot.skipped for slot in plan)

    def test_stress_case_narrow_window_skips_some_slots(self) -> None:
        profiles = [_profile(idx, preferred_time="09:00", jitter_minutes=0) for idx in range(1, 11)]
        config = _config(
            activity_window_start="09:00",
            activity_window_end="11:00",
            rest_min_minutes=30,
            rest_max_minutes=30,
        )
        plan = compute_daily_plan(profiles, config, date(2026, 4, 8), rng=Random(11))

        skipped = [slot for slot in plan if slot.skipped]
        assert len(plan) == 10
        assert len(skipped) > 0
        assert all(slot.skip_reason == "outside_activity_window" for slot in skipped)

    def test_window_clamping_applies_to_jittered_times(self) -> None:
        profiles = [_profile(1, preferred_time="07:15", jitter_minutes=0)]
        config = _config(activity_window_start="08:00", activity_window_end="20:00", rest_min_minutes=15, rest_max_minutes=15)
        plan = compute_daily_plan(profiles, config, date(2026, 4, 9), rng=Random(2))

        assert len(plan) == 1
        assert plan[0].scheduled_time == time(8, 0)

    def test_activity_window_crossing_midnight_raises(self) -> None:
        profiles = [_profile(1)]
        config = _config(activity_window_start="22:00", activity_window_end="02:00")
        with pytest.raises(ValueError, match="must not cross midnight"):
            compute_daily_plan(profiles, config, date(2026, 4, 9), rng=Random(1))

    def test_disabled_profiles_are_ignored(self) -> None:
        profiles = [_profile(1, enabled=False), _profile(2, enabled=True)]
        plan = compute_daily_plan(profiles, _config(), date(2026, 4, 9), rng=Random(4))
        assert [slot.profile_id for slot in plan] == [2]

    def test_string_profile_id_is_preserved(self) -> None:
        profiles = [_profile("morning", preferred_time="09:00")]
        plan = compute_daily_plan(profiles, _config(), date(2026, 4, 9), rng=Random(4))
        assert plan[0].profile_id == "morning"
