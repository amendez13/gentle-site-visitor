# gsv.visit

The visit layer lets applications describe what to do while the framework
injects the operational wrap from `docs/ARCHITECTURE.md` section 4.4 around
every step:

```text
cancellation_pre -> rate_limit -> execute -> content_wait -> delay -> burst_tick -> cancellation_post
```

## Built-In Steps

| Step | Purpose |
| --- | --- |
| `Navigate` | Load a URL with a Playwright `wait_until` mode. |
| `WaitFor` | Wait for a selector, with optional retry counting. |
| `Click` | Click a selector using jittered S1 primitives by default. |
| `Type` | Type text with human cadence. |
| `Scroll` | Scroll the page through S1 primitives. |
| `Dwell` | Simulate reading dwell time. |
| `Extract` | Run app-owned extraction logic and store the result. |
| `Branch` | Run one nested subtree based on a condition. |
| `ForEach` | Extract items and run a nested body per item. |
| `BurstCooldown` | Trigger or reset the burst governor explicitly. |
| `RecordEvent` | Write app-defined structured evidence. |

## First Plan

```python
plan = VisitPlan(
    steps=[
        Navigate("https://example.test", content_marker="main"),
        Extract(read_title, output_key="title"),
        RecordEvent("title_seen", lambda ctx: {"title": ctx.extracted["title"]}),
    ]
)
result = await VisitRunner(ctx).run(plan)
```

`NullEvidenceSink` is the default sink and does not touch the filesystem. S5
wires `JsonlEvidenceSink` into session bundles.
