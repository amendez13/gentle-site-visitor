# Scheduling

`gsv.schedule` is the macro-pacing layer. It decides when a worker should run
throughout a day; per-step request pacing still lives in `gsv.pacing`.

Schedule profiles are loaded from `visitor.schedule.profiles`:

```yaml
visitor:
  schedule:
    activity_window_start: "08:00"
    activity_window_end: "23:00"
    rest_min_minutes: 30
    rest_max_minutes: 90
    profiles:
      - id: morning
        name: Morning visit
        enabled: true
        frequency: weekdays
        preferred_time: "09:00"
        jitter_minutes: 30
```

Supported frequencies are `daily`, `weekdays`, `weekends`, or comma-separated
day abbreviations such as `mon,wed,fri`.

`compute_daily_plan()` is pure and accepts an injected `random.Random`, so
operators and tests can reproduce a plan with `gsv plan show --seed 42`.
Slots pushed beyond `activity_window_end` are retained in the plan but marked
`skipped` with `outside_activity_window`.

`SchedulingRunner` executes slots sequentially. In `gsv worker --schedule`,
each due slot creates a pending coordination run, claims that exact run, and
then executes it through `RunController.run_once()`.
