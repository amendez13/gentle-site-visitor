# S4 — Visit runner + steps

> **Slice:** S4 of 10. See [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md).
> **Architecture refs:** [ARCHITECTURE.md §4.4](../ARCHITECTURE.md#44-visit-layer-gsvvisit).
> **Status:** Implemented. **Depends on S1, S3.**

---

## 1. Goal

Build the visit layer: `VisitContext`, `VisitStep` protocol, `VisitPlan`, `VisitRunner`, and the built-in step library. The runner enforces the canonical wrap around every step:

```
1. cancellation.check(boundary=<step>_pre)
2. rate_limiter.acquire()
3. step.execute(ctx)
4. content_wait.maybe_run(page, step.content_marker)
5. delay_profile.sleep()
6. burst.tick()
7. cancellation.check(boundary=<step>_post)
```

After this slice, an integration test should be able to:

1. Construct a `VisitPlan` from a list of built-in steps.
2. Run it against the fixture server and observe gentle behavior between every step.
3. Use `Branch` and `ForEach` to express conditional and iterating flows.
4. Use `Extract` to pull data into a `VisitResult`.
5. Use `RecordEvent` to append a row to the per-run evidence stream (the file is created in S5; in S4 it can be a no-op pluggable sink).

S4 ships **no** session lifecycle, **no** observability bundle, **no** lease/cancel — those are S2/S5/S7. Cancellation hooks exist as `Callable | None` placeholders that S7 will plug.

---

## 2. Deliverables

### 2.1 New modules

| Path | Source | Notes |
|---|---|---|
| `src/gsv/visit/__init__.py` | new | Re-export public API. |
| `src/gsv/visit/context.py` | new | `VisitContext` dataclass + `VisitResult`. |
| `src/gsv/visit/plan.py` | new | `VisitPlan`, `VisitStep` protocol, `StepResult`. |
| `src/gsv/visit/runner.py` | new | `VisitRunner` with the canonical wrap. |
| `src/gsv/visit/steps/__init__.py` | new | Re-export all built-in steps. |
| `src/gsv/visit/steps/nav.py` | new (uses S1 primitives) | `Navigate`, `WaitFor`. |
| `src/gsv/visit/steps/act.py` | new (uses S1 primitives) | `Click`, `Type`, `Scroll`, `Dwell`. |
| `src/gsv/visit/steps/extract.py` | new | `Extract`. |
| `src/gsv/visit/steps/flow.py` | new | `Branch`, `ForEach`, `RecordEvent`. |
| `src/gsv/visit/steps/cooldown.py` | new | `BurstCooldown` explicit hint step. |
| `src/gsv/visit/sinks.py` | new | `EvidenceSink` protocol; `NullEvidenceSink` default; `JsonlEvidenceSink` (S5 wires this). |

### 2.2 New tests

| Path | Purpose |
|---|---|
| `tests/visit/test_runner.py` | Wrap order is exactly the seven steps above, in order; failure of any step is caught and recorded as a `StepResult.failure`; the runner emits framework-level counters. |
| `tests/visit/steps/test_nav.py` | `Navigate.execute` calls `page.goto` with the expected wait_until; `WaitFor.execute` uses the configured timeout. |
| `tests/visit/steps/test_act.py` | `Click` uses jitter when configured; `Type` uses `human_type`; `Scroll` and `Dwell` invoke the right primitives. |
| `tests/visit/steps/test_extract.py` | Async extractor receives `Page`; result is captured into `VisitResult`. |
| `tests/visit/steps/test_flow.py` | `Branch` evaluates condition once and runs only the chosen subtree; `ForEach` iterates with hydration retry; `RecordEvent` writes to the sink. |
| `tests/visit/test_hydration_retry.py` | `ForEach(hydration_retry=True)` retries an item once after `scroll_into_view_if_needed`; counters `hydration_retry_attempts`, `hydration_retry_success_count`, `hydration_retry_giveup_count` increment correctly. |
| `tests/visit/test_evidence_sink.py` | Default `NullEvidenceSink` accepts events; events are dropped silently. |

---

## 3. Reuse map

| CE source | Pattern | Bucket | Becomes | Notes |
|---|---|---|---|---|
| `src/scraper/jobs.py` | post-`goto` `wait_for_selector → random_delay → mouse_move` | **Reference** | Already encoded in S3's `ContentAwareWait`; the runner just calls it after each step. | — |
| `src/scraper/jobs.py` | per-card cooldown counter | **Reference** | Already encoded in S3's `BurstGovernor.tick()`. | — |
| `src/scraper/jobs.py` | virtualized list retry-after-scroll | **Reference** | `gsv/visit/steps/flow.py` `ForEach` `hydration_retry=True` branch. | The runtime checks for hydration hint on a per-iteration basis: if the per-iteration extract returns `EmptyResult.HYDRATION_NEEDED`, scroll the element into view, await briefly, retry once. |
| `src/scraper/jobs.py` | imperative loop structure (login → search → paginate → extract per card → cooldown) | **Reference** | Demonstrates that the step model is sufficient. We do NOT lift the loop body itself — it's CE-specific. | The S9 reference app rewrites a different shape entirely. |
| `src/scraper/auth.py` `human_type` usage | per-char | **Already in S1** | `gsv/visit/steps/act.py` `Type.execute` calls `human_type(page, selector, value)`. | — |

No CE source is **copied** in S4 — the visit runner is a new abstraction. The patterns it encodes were inlined throughout `jobs.py`. By making them declarative, we ensure every visit gets them uniformly.

---

## 4. Step-by-step

### Step 4.1 — Core types

`gsv/visit/context.py`:

```python
@dataclass
class VisitContext:
    page: Page
    session: Session
    pacing: Pacing
    config: VisitorConfig
    site: SiteConfig
    site_adapter: SiteAuthAdapter
    rng: random.Random
    sink: EvidenceSink
    cancellation: Cancellation | None = None  # plugged by S7
    extracted: dict[str, Any] = field(default_factory=dict)  # outputs of Extract steps

@dataclass
class VisitResult:
    outcome: Literal["completed", "failed", "cancelled", "blocked"]
    error: str | None
    counters: dict[str, int]
    extracted: dict[str, Any]
    step_results: list[StepResult]
```

`Cancellation` is a structural protocol with `check(force: bool = False, boundary: str = "") -> Awaitable[None]`. In S4 the runner accepts `cancellation=None` and skips the call. S7 supplies the real implementation.

### Step 4.2 — Step protocol and plan

`gsv/visit/plan.py`:

```python
class VisitStep(Protocol):
    name: str
    content_marker: str | None  # default None
    async def execute(self, ctx: VisitContext) -> StepResult: ...

@dataclass
class StepResult:
    name: str
    outcome: Literal["ok", "fail", "skip"]
    error: str | None = None
    extracted: Any = None
    duration_seconds: float = 0.0

@dataclass
class VisitPlan:
    steps: list[VisitStep | "VisitPlan"]
    outcome_classifier: Callable[[list[StepResult]], Literal["completed", "failed", "blocked"]] | None = None
```

`outcome_classifier` defaults to "completed if no step failed, else failed". Quality gates (e.g., "blocked" if zero items extracted) live here.

### Step 4.3 — Runner

`gsv/visit/runner.py`:

```python
class VisitRunner:
    def __init__(self, ctx: VisitContext): ...

    async def run(self, plan: VisitPlan) -> VisitResult: ...

    async def _run_step(self, step: VisitStep) -> StepResult:
        await self._cancel_check(f"{step.name}_pre")
        await self.ctx.pacing.rate_limiter.acquire()
        start = time.monotonic()
        try:
            result = await step.execute(self.ctx)
        except Exception as exc:
            result = StepResult(name=step.name, outcome="fail", error=str(exc))

        # post-execute wrap regardless of outcome:
        await self.ctx.pacing.content_wait.maybe_run(self.ctx.page, step.content_marker)
        await self.ctx.pacing.delay_profile.sleep()
        await self.ctx.pacing.burst.tick(boundary=f"{step.name}_burst")
        await self._cancel_check(f"{step.name}_post")

        result.duration_seconds = time.monotonic() - start
        return result

    async def _cancel_check(self, boundary: str) -> None:
        if self.ctx.cancellation is None:
            return
        await self.ctx.cancellation.check(boundary=boundary)
```

The runner emits framework-level counters into `VisitResult.counters`:

- `requests_made` (from rate-limiter accounting)
- `cooldowns` (number of times burst.tick slept)
- `cancellation_boundary_<name>_visited` (per boundary, optional — see Q1)
- `hydration_retry_attempts` / `hydration_retry_success_count` / `hydration_retry_giveup_count`

### Step 4.4 — Built-in steps (nav)

`gsv/visit/steps/nav.py`:

```python
@dataclass
class Navigate(VisitStep):
    url: str
    name: str = "navigate"
    content_marker: str | None = None
    wait_until: Literal["load", "domcontentloaded", "networkidle"] = "domcontentloaded"

    async def execute(self, ctx: VisitContext) -> StepResult:
        await ctx.page.goto(self.url, wait_until=self.wait_until)
        return StepResult(name=self.name, outcome="ok")

@dataclass
class WaitFor(VisitStep):
    selector: str
    name: str = "wait_for"
    content_marker: str | None = None
    timeout_ms: int = 10000

    async def execute(self, ctx: VisitContext) -> StepResult:
        await ctx.page.wait_for_selector(self.selector, timeout=self.timeout_ms)
        return StepResult(name=self.name, outcome="ok")
```

### Step 4.5 — Built-in steps (act)

`gsv/visit/steps/act.py`:

```python
@dataclass
class Click(VisitStep):
    selector: str
    name: str = "click"
    content_marker: str | None = None
    jitter: bool = True
    wait_for: str | None = None

    async def execute(self, ctx: VisitContext) -> StepResult:
        if self.jitter:
            ok = await click_with_position_jitter(ctx.page, self.selector)
        else:
            await ctx.page.click(self.selector)
            ok = True
        if self.wait_for:
            await ctx.page.wait_for_selector(self.wait_for)
        return StepResult(name=self.name, outcome="ok" if ok else "fail")

@dataclass
class Type(VisitStep):
    selector: str
    value: str
    name: str = "type"
    content_marker: str | None = None
    secret: bool = False  # if True, omit value from logs

    async def execute(self, ctx: VisitContext) -> StepResult:
        await human_type(ctx.page, self.selector, self.value)
        return StepResult(name=self.name, outcome="ok")

@dataclass
class Scroll(VisitStep):
    times: int = 1
    name: str = "scroll"
    content_marker: str | None = None

    async def execute(self, ctx: VisitContext) -> StepResult:
        await scroll_page(ctx.page, times=self.times)
        return StepResult(name=self.name, outcome="ok")

@dataclass
class Dwell(VisitStep):
    name: str = "dwell"
    content_marker: str | None = None
    min_seconds: float = 7.0
    max_seconds: float = 10.0

    async def execute(self, ctx: VisitContext) -> StepResult:
        elapsed = await run_humanized_page_dwell(ctx.page, min_seconds=self.min_seconds, max_seconds=self.max_seconds)
        return StepResult(name=self.name, outcome="ok", extracted=elapsed)
```

### Step 4.6 — Built-in steps (extract)

`gsv/visit/steps/extract.py`:

```python
@dataclass
class Extract(VisitStep):
    extractor: Callable[[Page], Awaitable[Any]]
    output_key: str
    name: str = "extract"
    content_marker: str | None = None

    async def execute(self, ctx: VisitContext) -> StepResult:
        value = await self.extractor(ctx.page)
        ctx.extracted[self.output_key] = value
        return StepResult(name=self.name, outcome="ok", extracted=value)
```

The extractor is a free async function. Apps own all parsing logic; the framework never inspects DOM beyond the runtime hooks.

### Step 4.7 — Built-in steps (flow)

`gsv/visit/steps/flow.py`:

```python
@dataclass
class Branch(VisitStep):
    condition: Callable[[VisitContext], Awaitable[bool]]
    then_steps: list[VisitStep]
    else_steps: list[VisitStep] = field(default_factory=list)
    name: str = "branch"
    content_marker: str | None = None

    async def execute(self, ctx: VisitContext) -> StepResult:
        chosen = self.then_steps if await self.condition(ctx) else self.else_steps
        # Run the chosen subtree through a nested runner so each sub-step gets the full wrap.
        sub_runner = VisitRunner(ctx)
        sub_result = await sub_runner.run(VisitPlan(steps=chosen))
        return StepResult(name=self.name, outcome=sub_result.outcome, extracted=sub_result.counters)

@dataclass
class ForEach(VisitStep):
    items_extractor: Callable[[Page], Awaitable[list[Any]]]
    body_factory: Callable[[Any], list[VisitStep]]   # given an item, build per-iteration steps
    name: str = "for_each"
    content_marker: str | None = None
    max_items: int | None = None
    hydration_retry: bool = False

    async def execute(self, ctx: VisitContext) -> StepResult: ...

@dataclass
class RecordEvent(VisitStep):
    event_type: str
    payload_factory: Callable[[VisitContext], dict[str, Any]]
    name: str = "record_event"
    content_marker: str | None = None

    async def execute(self, ctx: VisitContext) -> StepResult:
        payload = self.payload_factory(ctx)
        await ctx.sink.write(self.event_type, payload)
        return StepResult(name=self.name, outcome="ok")
```

`ForEach` is the most subtle. Its flow:

1. Call `items_extractor(page)` → list of N items.
2. Trim to `max_items` if set.
3. For each item:
   a. Build per-iteration steps via `body_factory(item)`.
   b. Run them through a nested `VisitRunner` (so they get the full wrap).
   c. If `hydration_retry=True` and the iteration's first extract returned the sentinel `EmptyResult.HYDRATION_NEEDED`, perform `page.locator(...).first.scroll_into_view_if_needed()` + `random_delay(0.5, 1.5)`, then retry the iteration body once. Bump `hydration_retry_attempts` always; `hydration_retry_success_count` on retry success; `hydration_retry_giveup_count` on retry failure.
4. Aggregate per-iteration `StepResult`s into the parent's `StepResult.extracted`.

### Step 4.8 — Built-in steps (cooldown)

`gsv/visit/steps/cooldown.py`:

```python
@dataclass
class BurstCooldown(VisitStep):
    """Explicit hint to the burst governor. Useful when the app knows a 'logical
    end of section' is here and wants to reset the counter."""
    reset: bool = False
    name: str = "burst_cooldown"
    content_marker: str | None = None

    async def execute(self, ctx: VisitContext) -> StepResult:
        if self.reset:
            ctx.pacing.burst.reset()
        else:
            await ctx.pacing.burst.tick(boundary="explicit_cooldown")
        return StepResult(name=self.name, outcome="ok")
```

`BurstGovernor.reset()` is a small addition to S3 — flag it as a tiny back-port to S3 if not already added (Q3).

### Step 4.9 — Sinks

`gsv/visit/sinks.py`:

```python
class EvidenceSink(Protocol):
    async def write(self, event_type: str, payload: dict[str, Any]) -> None: ...

class NullEvidenceSink:
    async def write(self, event_type: str, payload: dict[str, Any]) -> None:
        return None

class JsonlEvidenceSink:
    """Appends one JSON line per event to <session_dir>/evidence.jsonl."""
    def __init__(self, path: Path): ...
    async def write(self, event_type: str, payload: dict[str, Any]) -> None: ...
```

In S4 only the `Null` sink is wired by default. S5 sets `JsonlEvidenceSink` when observability mode produces a session dir.

### Step 4.10 — Documentation

- `src/gsv/visit/README.md`: runtime wrap diagram, list of built-in steps with one-line descriptions, "writing your first plan" example.

---

## 5. Acceptance criteria

- [ ] `pytest tests/visit` is green; coverage ≥ 90%.
- [ ] Unit test asserts the seven-step wrap order using a mock pacing object that records calls in order.
- [ ] `ForEach(hydration_retry=True)` correctly retries once and emits hydration counters.
- [ ] `Branch` runs only the chosen subtree (not both).
- [ ] `Extract` populates `ctx.extracted[output_key]` and the value appears in `VisitResult.extracted`.
- [ ] `RecordEvent` writes to the configured sink; `NullEvidenceSink` does not raise.
- [ ] No `gsv.run`, `gsv.observability`, `gsv.cli` imports from `gsv.visit`.
- [ ] `mypy src/gsv/visit` passes strict.

---

## 6. Out of scope (deferred)

- Real `Cancellation` implementation — S7. S4 ships the `Callable | None` placeholder seam.
- `JsonlEvidenceSink` is defined but not wired by default — S5 wires it.
- Quality gate logic beyond "no failed steps" — apps customize via `outcome_classifier` in S9; the framework offers a `MinExtractedCount(threshold)` helper in S10.

---

## 7. Dependencies

- Upstream: **S1**, **S3**.
- Downstream blockers: **S5** (uses `EvidenceSink`), **S7** (plugs `Cancellation`), **S9** (reference app).

---

## 8. Open questions

| ID | Question | Recommendation | Resolve in |
|---|---|---|---|
| Q1 | Should the runner emit a per-boundary counter? Risk of counter explosion. | No: emit a single `cancellation_checks_visited` counter (incremented on every check). Boundary names appear in trace events, not in counters. | S4 |
| Q2 | When `Branch.then_steps` is empty, what's the result? | `outcome="ok"`, no sub-steps run, no counters bumped. | S4 |
| Q3 | `BurstGovernor.reset()` — is this in S3 already? If not, back-port. | Back-port one-line method to S3's PR if S3 already shipped, otherwise include in S3. | S3 |
| Q4 | Should `Extract` be allowed to raise, or wrap exceptions in `StepResult.failure`? | The runner already catches exceptions. Let `Extract` raise normally; the runner's `try/except` in `_run_step` produces a clean `StepResult(outcome="fail", error=...)`. | S4 |

---

## 9. Reviewer checklist

- [ ] Every built-in step calls only S1 primitives or S3 pacing — no direct `time.sleep`, `asyncio.sleep`, or unrandomized waits.
- [ ] The runner wraps every step (not just first-level) — verified by `Branch`/`ForEach` tests.
- [ ] No site-specific selectors or URLs in `gsv/visit/`.
- [ ] `EvidenceSink.write` is async (apps may write to a remote system).
- [ ] `VisitContext.cancellation: Cancellation | None` is the exact name S7 will use.
