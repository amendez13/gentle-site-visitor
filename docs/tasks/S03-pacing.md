# S3 — Pacing

> **Slice:** S3 of 10. See [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md).
> **Architecture refs:** [ARCHITECTURE.md §4.3](../ARCHITECTURE.md#43-pacing-layer-gsvpacing).
> **Status:** Implemented. **Depends on S1.**

---

## 1. Goal

Promote the per-action gentle behaviors built in S1 from raw helpers into named, composable, configurable profiles. The visit runner (S4) will wrap every step with these so applications never thread delays manually.

After this slice, an integration test should be able to:

1. Build a `Pacing` aggregate (`{delay_profile, burst_governor, rate_limiter, content_wait}`) from `VisitorConfig` + `SiteConfig`.
2. Sample 1000 delays from `DelayProfile("production")` and observe the distribution: ~90% in `[2.0, 5.0]`, ~10% in `[15.0, 45.0]`, mean ~ 6.5s.
3. Tick a `BurstGovernor(interval=5, cooldown_range=(30, 90))` five times and observe a sleep on the 5th tick.
4. Call `ContentAwareWait.maybe_run(page, content_marker)` and observe `wait_for_selector` + a small reaction delay + an optional mouse move.
5. Replace any of the above with a no-op via configuration (`pacing.profile=disabled`) for tests.

S3 ships **only** the pacing primitives. The visit runner that uses them is S4.

---

## 2. Deliverables

### 2.1 New modules

| Path | Source | Notes |
|---|---|---|
| `src/gsv/pacing/__init__.py` | new | Re-export `DelayProfile`, `BurstGovernor`, `ContentAwareWait`, `Pacing`. |
| `src/gsv/pacing/delay_profile.py` | new (compose `human_delay` from S1) | Named profiles registry + sampling. |
| `src/gsv/pacing/burst.py` | new (extracted from CE config + jobs.py usage) | `BurstGovernor` with action counter and cooldown. |
| `src/gsv/pacing/content_wait.py` | new (extracted from CE jobs.py post-`goto` pattern) | `ContentAwareWait`. |
| `src/gsv/pacing/aggregate.py` | new | `Pacing` namedtuple/dataclass binding the above plus `RateLimiter` (from S1) for downstream injection. |

Extend `src/gsv/config/model.py`:

- `PacingConfig.profile: str = "production"`
- `PacingConfig.profiles: dict[str, DelayProfileSpec]` — registry of available profiles. Defaults below.
- `PacingConfig.burst_cooldown_interval: int = 5`
- `PacingConfig.burst_cooldown_range: tuple[float, float] = (30.0, 90.0)`
- `PacingConfig.content_wait_timeout_ms: int = 10000`
- `PacingConfig.content_wait_reaction_range: tuple[float, float] = (0.5, 1.5)`
- `PacingConfig.content_wait_with_mouse_move: bool = True`

`DelayProfileSpec` is a dataclass:

```python
@dataclass(frozen=True)
class DelayProfileSpec:
    min_seconds: float
    max_seconds: float
    distraction_chance: float = 0.0
    distraction_min_seconds: float = 0.0
    distraction_max_seconds: float = 0.0
```

Default registry (matches CE behavior):

| Name | min | max | dist% | dist_min | dist_max | Notes |
|---|---|---|---|---|---|---|
| `production` | 2.0 | 5.0 | 0.10 | 15.0 | 45.0 | The default per-step pacing. |
| `recon` | 0.8 | 1.8 | 0.0 | — | — | Equivalent of CE `panel_probe_delay_range`. |
| `auth` | 0.5 | 1.0 | 0.0 | — | — | Login flow short delays. Used by S2 once S3 is integrated. |
| `disabled` | 0.0 | 0.0 | 0.0 | — | — | Tests only. |

### 2.2 New tests

| Path | Purpose |
|---|---|
| `tests/pacing/test_delay_profile.py` | Distribution test under seeded RNG; profile registry lookup; `disabled` profile is a no-op; custom app-defined profile registers and resolves. |
| `tests/pacing/test_burst.py` | After exactly `interval` ticks, the next tick sleeps; cooldown duration is in `cooldown_range`; cancellation hook (Q1) is invoked before sleep. |
| `tests/pacing/test_content_wait.py` | `maybe_run` is a no-op when `content_marker is None`; calls `wait_for_selector` with the configured timeout; reaction delay sampled; mouse move toggled by config. |
| `tests/pacing/test_aggregate.py` | Builder constructs `Pacing` from config; resolves profile name; injects `RateLimiter` from `BrowserManager`. |

---

## 3. Reuse map

| CE source | CE lines | Bucket | Becomes | Notes |
|---|---|---|---|---|
| `src/scraper/browser.py` | 78–91 (`human_delay`) | **Reference** | `gsv/pacing/delay_profile.py` `DelayProfile.sleep()` | S1 keeps the raw function. S3 wraps it: a `DelayProfile` instance, given a name, samples from the spec and sleeps. The function-level helper stays for places that want a one-off (S2 auth flow, debug). |
| `src/config.py` `ScraperConfig.burst_cooldown_interval`, `burst_cooldown_range` | per-field | **Reference** | `gsv/config/model.py` `PacingConfig` | Field names match. CE used `[float, float]` JSON → tuple. |
| `src/config.py` `ScraperConfig.panel_probe_delay_range` | per-field | **Reference** | Default `recon` profile | The numeric range is the CE evidence; the new abstraction is profile-named. |
| `src/scraper/jobs.py` (per-card cooldown loop, `if cards_processed % burst_interval == 0:`) | search by pattern (CE file too large to read here; pattern documented in [notes/_findings.md](../../notes/_findings.md)) | **Reference** | `gsv/pacing/burst.py` | The pattern: increment counter, on `count % interval == 0` sleep `uniform(*cooldown_range)`. We make this an object so the visit runner doesn't re-implement it. |
| `src/scraper/jobs.py` post-`goto` pattern: `wait_for_selector → random_delay(0.5,1.5) → maybe random_mouse_move` | by pattern | **Reference** | `gsv/pacing/content_wait.py` | Encode the pattern once. |

No CE code is **copied** in S3 — everything here is **reference**, because the pacing layer is a new abstraction that didn't exist as standalone code in CE (it was inlined throughout `jobs.py`).

---

## 4. Step-by-step

### Step 3.1 — DelayProfile

`gsv/pacing/delay_profile.py`:

```python
class DelayProfile:
    def __init__(self, name: str, spec: DelayProfileSpec, rng: random.Random | None = None): ...

    async def sleep(self) -> float:
        # Returns the actual delay slept, for telemetry.
        ...

    @classmethod
    def from_registry(cls, name: str, registry: Mapping[str, DelayProfileSpec], rng: random.Random | None = None) -> DelayProfile:
        if name not in registry:
            raise KeyError(f"Unknown delay profile: {name!r}")
        return cls(name, registry[name], rng=rng)
```

Implementation reuses S1's `human_delay` semantics but without the function-level closure on RNG (the profile owns RNG). The `disabled` profile short-circuits to `await asyncio.sleep(0)` and returns `0.0`.

Tests: with `Random(42)` seeded RNG, sample 1000 delays from `production` and assert ~10% land in `[15, 45]`, mean within tolerance.

### Step 3.2 — BurstGovernor

`gsv/pacing/burst.py`:

```python
class BurstGovernor:
    def __init__(
        self,
        *,
        interval: int,
        cooldown_range: tuple[float, float],
        rng: random.Random | None = None,
        on_pre_cooldown: Callable[[str], Awaitable[None]] | None = None,
    ): ...

    @property
    def actions_since_last_cooldown(self) -> int: ...

    async def tick(self, *, boundary: str = "burst") -> float:
        """
        Increment the action counter. If a cooldown fires, await it.
        Returns the slept duration (0.0 if no cooldown).
        Calls `on_pre_cooldown(boundary)` before sleeping (used by S7 for cancellation check).
        """
```

The `on_pre_cooldown` hook is the cancellation seam — S7 will plug `cancellation.check(boundary="before_burst_cooldown")` here. In S3 it's an injected `Callable | None`; defaulted to `None`.

### Step 3.3 — ContentAwareWait

`gsv/pacing/content_wait.py`:

```python
class ContentAwareWait:
    def __init__(
        self,
        *,
        timeout_ms: int,
        reaction_range: tuple[float, float],
        with_mouse_move: bool,
        rng: random.Random | None = None,
    ): ...

    async def maybe_run(
        self,
        page: Page,
        content_marker: str | None,
    ) -> None:
        if content_marker is None:
            return
        await page.wait_for_selector(content_marker, timeout=self._timeout_ms)
        await random_delay(*self._reaction_range)
        if self._with_mouse_move:
            await random_mouse_move(page)
```

`random_delay` and `random_mouse_move` come from `gsv.browser.primitives` (S1).

### Step 3.4 — Pacing aggregate

`gsv/pacing/aggregate.py`:

```python
@dataclass(frozen=True)
class Pacing:
    delay_profile: DelayProfile
    burst: BurstGovernor
    content_wait: ContentAwareWait
    rate_limiter: RateLimiter

def build_pacing(
    visitor: VisitorConfig,
    site: SiteConfig,
    rate_limiter: RateLimiter,
    rng: random.Random | None = None,
) -> Pacing: ...
```

`build_pacing` is the only entry point S4 needs; later S7 may pass a different `RateLimiter` if it ever switches to per-worker shared limiting (out of scope v0).

### Step 3.5 — Resolve TODOs in S2

Once S3 lands, replace S2's `random_delay(0.5, 1.0)` placeholders with `auth_delay_profile.sleep()`. The `Session` constructor takes `pacing: Pacing` and uses `pacing.delay_profile_for("auth")` (or accepts a separate `auth_profile` parameter — see Q2).

This step is part of S3's PR — do not leave the TODOs orphaned across slices.

### Step 3.6 — Documentation

- `src/gsv/pacing/README.md`: composition rule from [ARCHITECTURE.md §4.3](../ARCHITECTURE.md#43-pacing-layer-gsvpacing), profile registry table, how to register a custom profile.

---

## 5. Acceptance criteria

- [ ] `pytest tests/pacing` is green; coverage ≥ 95% (this layer has minimal I/O).
- [ ] Default profile registry matches the CE numbers exactly: `production=(2.0, 5.0, 0.10, 15.0, 45.0)`, `recon=(0.8, 1.8, ...)`, `auth=(0.5, 1.0, ...)`, `disabled=(0.0, 0.0, ...)`.
- [ ] `BurstGovernor` with `interval=5` does NOT sleep on ticks 1-4, sleeps on tick 5, and the cooldown duration is within `cooldown_range`.
- [ ] `ContentAwareWait.maybe_run(page, None)` does not call `wait_for_selector`.
- [ ] `Pacing` is constructed entirely from config + injected RNG; no module-level `random.uniform` calls in `gsv.pacing.*`.
- [ ] `gsv.session.Session` no longer carries `# TODO(S3)` markers.
- [ ] `mypy src/gsv/pacing` passes strict.

---

## 6. Out of scope (deferred)

- Cancellation integration with `BurstGovernor` (the `on_pre_cooldown` hook exists but is unused) — **S7**.
- Visit runner that wraps every step with `Pacing` — **S4**.
- Custom user-registered profiles via plugin entry point — out of scope v0; profiles can be added in `config.yaml` only.

---

## 7. Dependencies

- Upstream: **S1** (primitives, RateLimiter).
- Downstream blockers: **S4** (visit runner), **S7** (cancellation seam).

---

## 8. Open questions

| ID | Question | Recommendation | Resolve in |
|---|---|---|---|
| Q1 | Should `BurstGovernor.tick()` block on cooldown immediately, or schedule the cooldown for the *next* `tick()` to give the runner a chance to check cancellation in between? | Block immediately. The `on_pre_cooldown` hook gives the cancellation seam a chance before sleep. Splitting tick→cooldown across two calls makes the abstraction harder to reason about. | S3 |
| Q2 | Does `Session` get a single `Pacing` and pick `auth` from `delay_profile_for("auth")`, or a dedicated `auth_profile: DelayProfile`? | Dedicated `auth_profile` argument: explicit > clever. The visit runner gets the full `Pacing`; the `Session` only needs one profile. | S3 |
| Q3 | Does `disabled` profile's `await asyncio.sleep(0)` actually yield? Is there a test risk? | Use `await asyncio.sleep(0)` so `asyncio` event loop yields once. Document explicitly. | S3 |

---

## 9. Reviewer checklist

- [ ] No magic numbers in `gsv.pacing.*`. Every number traces to a `PacingConfig` field or a `DelayProfileSpec`.
- [ ] RNG is injectable everywhere; defaulted constructors are tested for determinism.
- [ ] `S2`'s TODO markers are gone after this PR.
- [ ] Module docstrings reference [ARCHITECTURE.md §4.3](../ARCHITECTURE.md#43-pacing-layer-gsvpacing).
- [ ] No imports from `gsv.visit`, `gsv.run`, or other downstream layers.
