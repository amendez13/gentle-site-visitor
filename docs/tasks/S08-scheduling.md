# S8 — Scheduling

> **Slice:** S8 of 10. See [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md).
> **Architecture refs:** [ARCHITECTURE.md §4.6](../ARCHITECTURE.md#46-scheduling-layer-gsvschedule).
> **Status:** Not started. **Depends on S7.**

---

## 1. Goal

Decide *when* runs fire across a day so they look human, not cron-clockwork. Port CareerExplorer's pure planner (`src/orchestrator_plan.py`) into `gsv.schedule.plan` essentially verbatim — it's already site-agnostic, RNG-injectable, and thoroughly tested. Wire the resulting `PlannedSlot` list into `gsv worker` (claim-when-due) and into `gsv plan show` (S6 placeholder gets a real implementation).

After this slice, an integration test should be able to:

1. Define a list of profiles in YAML (`name`, `frequency`, `preferred_time`, `jitter_minutes`).
2. Call `compute_daily_plan(profiles, config, target_date, rng=Random(42))` and observe a deterministic, jittered, rest-period-enforced sorted slot list.
3. Run `gsv plan show --site example --date 2026-05-04 --seed 42` and see the same plan printed.
4. Run `gsv worker --site example --schedule` (a new flag) and observe the worker waking up at each scheduled slot, claiming a run, and idling between slots.

---

## 2. Deliverables

### 2.1 New modules

| Path | Source | Notes |
|---|---|---|
| `src/gsv/schedule/__init__.py` | new | Re-export `PlannedSlot`, `compute_daily_plan`, `matches_day`, `compute_jittered_time`, `enforce_rest_periods`, `clamp_to_window`. |
| `src/gsv/schedule/plan.py` | from CE `src/orchestrator_plan.py` lines 1–214 (Copy) | Near-verbatim port. |
| `src/gsv/schedule/profile.py` | new | `ScheduleProfile` dataclass (typed wrapper for the YAML rows the planner consumes as `Mapping`). |
| `src/gsv/schedule/runner.py` | new | `SchedulingRunner` — wakes at each slot, calls `RunController.run_once()` for the slot's profile. |

### 2.2 Modules to update

| Path | Change |
|---|---|
| `src/gsv/cli/plan.py` (S6 placeholder) | Real implementation: load profiles, compute plan, print table. |
| `src/gsv/cli/worker.py` (S7) | Add `--schedule` flag. When set, the worker runs in scheduled mode (idle until next slot, then `run_once()`). When omitted, the original poll-based behavior is preserved. |
| `src/gsv/config/model.py` | Add `ScheduleConfig` (already sketched in [ARCHITECTURE.md §4.8](../ARCHITECTURE.md#48-configuration-gsvconfig)): `activity_window_start`, `activity_window_end`, `rest_min_minutes`, `rest_max_minutes`, `profiles: list[ScheduleProfile]`. |

### 2.3 New tests

| Path | Purpose |
|---|---|
| `tests/schedule/test_plan.py` | Port the existing CE tests for `compute_daily_plan` (CE has these tests under `tests/test_orchestrator_plan.py` or similar — confirm path during slice work and lift). Cover: jitter determinism with seeded RNG, weekday-only frequency, rest-period push, slots dropped when window overflows, empty profiles. |
| `tests/schedule/test_runner.py` | `SchedulingRunner` sleeps until next slot, then calls `RunController.run_once()`; on slot completion, advances to the next; honors Ctrl-C cleanly. |
| `tests/cli/test_plan_show.py` | `gsv plan show --date 2026-05-04 --seed 42` produces a deterministic table; `--json` emits structured output. |

---

## 3. Reuse map

| CE source | CE lines | Bucket | Becomes | Generalization |
|---|---|---|---|---|
| `src/orchestrator_plan.py` | 1–214 (entire file) | **Copy** | `gsv/schedule/plan.py` | Mechanical only: drop `from __future__ import annotations` (already standard), preserve every public function. The file is already pure (no I/O, no DB, RNG-injectable). The only behavioral diff: CE uses `profile_id: int`; we accept `profile_id: int | str` (Q1 below). |
| CE tests for `orchestrator_plan` | (locate during slice work) | **Copy** | `tests/schedule/test_plan.py` | Mechanical: rewrite imports; otherwise a 1:1 port. |

`PlannedSlot` already has the right shape:

```python
@dataclass
class PlannedSlot:
    profile_id: int | str    # was int in CE
    profile_name: str
    scheduled_time: time
    original_time: time
    skipped: bool = False
    skip_reason: str | None = None
```

---

## 4. Step-by-step

### Step 8.1 — Port the planner

Copy `src/orchestrator_plan.py` to `src/gsv/schedule/plan.py`. Diff:

```diff
- """Pure planning logic for daily orchestrator execution windows."""
+ """Pure planning logic for daily Gentle Site Visitor execution windows."""

  from dataclasses import dataclass
  from datetime import date, time
  from random import Random
  from typing import Any, Mapping
```

Optional: tighten type of `profile_id` to `int | str`. Keep all helper signatures (`_parse_hhmm`, `_time_to_minutes`, `_minutes_to_time`, `_coerce_int`, `_get_field`, `matches_day`, `compute_jittered_time`, `clamp_to_window`, `enforce_rest_periods`, `compute_daily_plan`) intact. This ensures CE's existing test suite ports cleanly.

### Step 8.2 — Profile dataclass

`src/gsv/schedule/profile.py`:

```python
@dataclass(frozen=True)
class ScheduleProfile:
    id: int | str
    name: str
    enabled: bool = True
    frequency: str = "daily"        # "daily" | "weekdays" | "weekends" | "mon,tue,..."
    preferred_time: str = "09:00"   # HH:MM
    jitter_minutes: int = 30
```

The planner accepts `Mapping[str, Any]` — `ScheduleProfile` is just a typed loader-side helper.

### Step 8.3 — Loader

Extend `src/gsv/config/loader.py`: parse `visitor.schedule.profiles` (a list of dicts) into `list[ScheduleProfile]`. Validation errors raise with clear messages (config error → exit 20).

### Step 8.4 — Scheduling runner

`src/gsv/schedule/runner.py`:

```python
class SchedulingRunner:
    def __init__(
        self,
        *,
        config: VisitorConfig,
        site: str,
        run_controller_factory: Callable[[], RunController],
        clock: Clock = SystemClock(),
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ): ...

    async def run_today(self, *, target_date: date, rng: random.Random | None = None) -> int: ...

    async def run_forever(self) -> int: ...
```

`run_today` computes the plan, then for each non-skipped slot: sleep until scheduled time, call `RunController.run_once()`, on completion or failure record the outcome and continue. Errors per slot don't kill the day — a single failed run logs and the loop moves to the next slot.

`run_forever` rolls over at midnight: at end-of-day, recompute for tomorrow and continue.

The injected `clock` and `sleeper` make the runner unit-testable without real time.

### Step 8.5 — CLI: real `gsv plan show`

Replace the S6 placeholder:

```python
@click.command("show")
@click.option("--site", required=False, help="Show only profiles for this site.")
@click.option("--date", "date_str", default=None, help="YYYY-MM-DD (default: today UTC).")
@click.option("--seed", default=None, type=int, help="Seed RNG for reproducible output.")
@click.option("--json", "as_json", is_flag=True, default=False)
@click.pass_context
def show_command(ctx, site, date_str, seed, as_json): ...
```

Output table columns: `PROFILE  SCHEDULED  ORIGINAL  STATUS  SKIP_REASON`.

### Step 8.6 — CLI: `gsv worker --schedule`

```python
@click.option("--schedule/--poll", default=False)
```

`--schedule` constructs a `SchedulingRunner`; `--poll` (default) preserves the S7 poll-based loop. The two modes are mutually exclusive in the user's mental model: poll = reactive, schedule = predictive.

### Step 8.7 — Integration with the worker control flow

When in `--schedule` mode:

1. At each slot's scheduled time, the worker calls `lease_client.claim(profile_id_or_run_id)` — but the dev server expects a *run id*, not a profile id. There's a mapping decision (Q2): does the server pre-create runs from profiles (push model), or does the worker create a run when a slot fires (pull model)?
2. **Recommendation: pull model.** When a slot fires, the worker calls a new endpoint `POST /api/runs?from_profile=<profile_id>&site=<site>` to mint a fresh run, then claims it. This keeps profiles a worker-side concept and the server stateless about scheduling. Add `POST /api/runs` to S7's dev server in this slice.

Updated dev server endpoint added in S8:

```
POST /api/runs                            # body: {profile_id, site, parameters_overrides}
                                          # → {id, ...}
```

### Step 8.8 — Documentation

- `src/gsv/schedule/README.md`: examples of profile YAML, behavior of `frequency`, jitter, rest periods.
- Update [ARCHITECTURE.md §14](../ARCHITECTURE.md#14-open-questions) Q4 (schedule source of truth) — mark resolved: YAML profiles for v0; DB-backed deferred.

---

## 5. Acceptance criteria

- [ ] `pytest tests/schedule tests/cli/test_plan_show.py` green; coverage ≥ 95% on `gsv.schedule.*` (the module is pure; no excuse for low coverage).
- [ ] `compute_daily_plan(profiles, config, date, rng=Random(42))` produces identical output across runs.
- [ ] Slots that would land outside `activity_window_end` are marked `skipped="outside_activity_window"`.
- [ ] Rest-period enforcement: with `rest_min=30, rest_max=90` and three profiles preferring `10:00`, the second and third are pushed forward.
- [ ] `gsv plan show --seed 42` produces deterministic output; `--json` emits a stable schema.
- [ ] `gsv worker --schedule` honors Ctrl-C cleanly between slots (no orphaned `BrowserManager`).
- [ ] No `linkedin`, `task`, or `vps` strings in `gsv/schedule/`.

---

## 6. Out of scope (deferred)

- Cross-midnight activity windows.
- Per-day variations (e.g., "weekday rest min different from weekend").
- DB-backed profiles — kept on the open-questions list. v0 is YAML-only.
- Holiday calendars / freeze windows — apps can implement by toggling `enabled`.

---

## 7. Dependencies

- Upstream: **S7** (`RunController` and dev server's `POST /api/runs` extension).
- Downstream blockers: **S9** (reference app uses scheduled runs).

---

## 8. Open questions

| ID | Question | Recommendation | Resolve in |
|---|---|---|---|
| Q1 | `profile_id` int vs string? | Accept `int | str`. Some apps will want UUID-like ids. | S8 |
| Q2 | Pull vs push run creation when slot fires? | Pull (worker creates a run on slot fire). Server stays scheduling-agnostic. | S8 |
| Q3 | Should `SchedulingRunner` honor the rate limiter as well, or only profile schedules? | Only schedules. The per-run `BrowserManager.RateLimiter` already governs requests. The scheduler is the "macro" pacing layer. | S8 |
| Q4 | If a slot fires while the previous slot's run is still executing, queue, drop, or run concurrently? | Queue. The architecture says one session at a time per worker; concurrent slots violate that. Queueing keeps the operator's mental model intact. | S8 |

---

## 9. Reviewer checklist

- [ ] `gsv/schedule/plan.py` is byte-for-byte equivalent to CE except for module docstring and (optional) `profile_id` widening.
- [ ] CE's existing planner test suite is ported and passes.
- [ ] `--seed` makes `gsv plan show` reproducible.
- [ ] `--schedule` mode has a Ctrl-C test that asserts clean shutdown.
- [ ] `POST /api/runs` is added to the dev server with admin-only auth.
- [ ] No imports from `gsv.run` inside `gsv.schedule.plan` (keeps the planner pure).
