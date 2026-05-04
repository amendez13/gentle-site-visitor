# S1 — Browser + primitives

> **Slice:** S1 of 10. See [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) for the slice index.
> **Architecture refs:** [ARCHITECTURE.md §4.1](../ARCHITECTURE.md#41-browser--fingerprint-layer-gsvbrowser), [§7 module layout](../ARCHITECTURE.md#7-module-layout), [§9 anti-bot stance](../ARCHITECTURE.md#9-anti-bot-stance-in-depth).
> **Status:** Implemented in the S1 browser-layer branch.

---

## 1. Goal

Stand up the bottom layer of the framework: a `BrowserManager` that owns a Playwright Chromium browser/context with aligned fingerprint, plus the human-cadence interaction primitives (`random_delay`, `human_delay`, `random_mouse_move`, `click_with_position_jitter`, `human_type`, `scroll_page`, `run_humanized_page_dwell`) and the per-hour `RateLimiter`.

After this slice, an integration test should be able to:

1. Construct a `BrowserManager` from a `VisitorConfig` + `SiteConfig`.
2. Start a browser, navigate to a fixture page, perform a human-typed input, and capture screenshots.
3. Save and restore `storage_state` across two `BrowserManager` lifecycles.
4. Honor a per-hour rate cap by blocking on `new_page()`.

S1 ships with **no** session/auth flow, **no** observability bundle, **no** visit runner. Those are S2/S5/S4.

---

## 2. Deliverables

### 2.1 New package + modules

| Path | Source | Notes |
|---|---|---|
| `src/gsv/__init__.py` | new | Empty; package marker. |
| `src/gsv/browser/__init__.py` | new | Re-export `BrowserManager`, primitives, `RateLimiter`. |
| `src/gsv/browser/primitives.py` | from CE `src/scraper/browser.py` lines 22–198 | Pure helpers (`STEALTH_LAUNCH_ARGS`, `WEBDRIVER_INIT_SCRIPT`, `random_delay`, `human_delay`, `random_mouse_move`, `click_with_position_jitter`, `run_humanized_page_dwell`, `human_type`, `scroll_page`, `ViewportSize`). |
| `src/gsv/browser/rate_limit.py` | from CE `src/scraper/browser.py` lines 43–69 | `RateLimiter` dataclass (sliding-window per-hour). |
| `src/gsv/browser/fingerprint.py` | from CE `src/scraper/browser.py` lines 216–245 | `build_user_agent(browser_version, platform)` and `build_viewport(rng, width_range, height_range)` extracted as pure functions. |
| `src/gsv/browser/manager.py` | from CE `src/scraper/browser.py` lines 201–543 | `BrowserManager` adapted to the new config shape. |
| `src/gsv/config/__init__.py` | new | Re-export model + loader stubs. |
| `src/gsv/config/model.py` | new (referencing CE `src/config.py` `ScraperConfig`) | `VisitorConfig`, `SiteConfig`, `PacingConfig`, `FingerprintConfig`, `ObservabilityConfig`, `WorkerConfig`. **S1 only needs the fields touched by `BrowserManager`**: `headless`, `storage_path`, `locale`, `timezone_id`, `page_timeout_seconds`, `pacing.rate_limit_per_hour`, `fingerprint.viewport_*_range`, `observability.{mode,trace,har,video,sessions_dir,har_content}` (the last block is read but not yet acted on — S5 wires it). |
| `src/gsv/config/loader.py` | new | Minimal YAML loader with `${ENV}` interpolation and per-site override merge. Sufficient to feed `BrowserManager`. |

### 2.2 New tests

| Path | Purpose |
|---|---|
| `tests/browser/test_primitives.py` | Unit tests for `random_delay`/`human_delay` distribution under seeded RNG; `RateLimiter` sliding-window correctness; `random_mouse_move` viewport-padding math; `human_type` per-char delay; helper resilience to missing viewport. |
| `tests/browser/test_rate_limit.py` | Sliding-window prune behavior, blocking acquire under saturation, `remaining` accounting. |
| `tests/browser/test_fingerprint.py` | UA construction across darwin / linux / windows; viewport randomization within configured ranges; major-version fallback when `browser.version` is empty. |
| `tests/browser/test_manager.py` | End-to-end against a local fixture HTTP server (added in `tests/fixtures/server.py`): start → `new_page` → goto → save_session → close → restart → confirm storage state is honored; `_build_context_kwargs` shape; HAR/video kwargs absent until S5. |
| `tests/fixtures/server.py` | Tiny `aiohttp` (or `http.server`) fixture serving a few canned HTML pages. Reused by S2/S4 too. |
| `tests/conftest.py` | Already exists from template; add fixture for `tmp_path`-rooted `VisitorConfig`. |

---

## 3. Reuse map (CareerExplorer → gsv)

| CE source | CE lines | Bucket | Becomes | Generalization required |
|---|---|---|---|---|
| `src/scraper/browser.py` | 22–33 (`STEALTH_LAUNCH_ARGS`, `WEBDRIVER_INIT_SCRIPT`) | **Copy** | `gsv/browser/primitives.py` top | None |
| `src/scraper/browser.py` | 36–41 (`ViewportSize`) | **Copy** | `gsv/browser/primitives.py` | None |
| `src/scraper/browser.py` | 43–69 (`RateLimiter`) | **Copy** | `gsv/browser/rate_limit.py` | None |
| `src/scraper/browser.py` | 72–198 (`random_delay`, `human_delay`, `random_mouse_move`, `click_with_position_jitter`, `run_humanized_page_dwell`, `human_type`, `scroll_page`) | **Copy** | `gsv/browser/primitives.py` | None functionally; drop `from src.config import ScraperConfig` (these helpers are config-free). |
| `src/scraper/browser.py` | 216–245 (`_build_user_agent`, `_build_viewport`) | **Adapt** | `gsv/browser/fingerprint.py` | Promote to module-level pure functions. Pass `browser_version` and `platform` (or RNG) explicitly so `BrowserManager` no longer owns the random source for fingerprint computation. Replace hardcoded `1260-1380 × 780-900` with config-supplied ranges. |
| `src/scraper/browser.py` | 201–215 (`BrowserManager.__init__`) | **Adapt** | `gsv/browser/manager.py` | Accept `VisitorConfig` + `SiteConfig` (not `ScraperConfig`). `RateLimiter` reads `visitor.pacing.rate_limit_per_hour`. Remove session-id stamping (`init_session`) and tracing/HAR/video methods → those belong to S5; leave private hooks (`_session_dir`, `_tracing_active`, etc.) **out** of S1. |
| `src/scraper/browser.py` | 247–308 (`session_dir`, `session_id`, `init_session`, `get_browser_metadata`, `_build_context_kwargs`) | **Adapt** | `gsv/browser/manager.py` | Keep `_build_context_kwargs` minus HAR/video kwargs. `get_browser_metadata` stays for use by S5. `init_session`/`session_dir`/`session_id` move to S5's `SessionRecorder`. |
| `src/scraper/browser.py` | 284–308 (`_build_context_kwargs`) | **Adapt** | `gsv/browser/manager.py` | **Critical generalization:** the hardcoded `record_har_url_filter = "**/*linkedin.com/**"` becomes `site.allowed_host_globs[0]` (or a list-aware filter — see Open question Q1 below). HAR fields stay omitted in S1 by skipping the `har_path` branch entirely. |
| `src/scraper/browser.py` | 310–337 (`_apply_context_defaults`, `start`) | **Copy** | `gsv/browser/manager.py` | Replace `self.config.session_path` with `self._site.storage_path` resolved against `visitor.storage_path` template. |
| `src/scraper/browser.py` | 339–500 (`start_tracing`, `stop_tracing`, `enable_har_for_session`, `finalize_har`, `finalize_video`, `_promote_video_files`, `_cleanup_video_dir`, `har_path`, `cleanup_artifacts_on_success`) | **Defer to S5** | — | Do not lift in S1. They depend on `_session_dir` which S5 introduces. |
| `src/scraper/browser.py` | 502–541 (`save_session`, `new_page`, `close`) | **Copy** | `gsv/browser/manager.py` | Replace `self.config.session_path` with the site-resolved storage path. `close()` stays simple (no tracing in S1). |
| `src/scraper/browser.py` | 545–556 (`cleanup_session_artifacts_on_success`) | **Defer to S5** | — | Lives in observability. |
| `src/config.py` `ScraperConfig` | per-field | **Reference** | `gsv/config/model.py` `VisitorConfig` etc. | Read field-by-field; only carry forward what S1 needs. CE specifics (LinkedIn email/password, search-task knobs, panel-probe ranges) are dropped. |
| `src/config.py` loader (env interpolation) | per-line | **Reference** | `gsv/config/loader.py` | Reimplement minimally; keep `${ENV}` and `~` expansion semantics. |

---

## 4. Step-by-step

Work in this order; each step is a self-contained commit.

### Step 1.1 — Lay down the package skeleton

- Create `src/gsv/__init__.py`, `src/gsv/browser/__init__.py`, `src/gsv/config/__init__.py`.
- Add `gsv` to `pyproject.toml` `[tool.setuptools.packages.find]` (or whatever the template uses).
- Add `playwright` and `pyyaml` to `requirements.txt`.
- Add a no-op test (`tests/test_smoke.py::test_imports`) importing `gsv` and `gsv.browser` to prove packaging works.

### Step 1.2 — Configuration model (S1 subset)

- Implement `gsv/config/model.py` with the dataclasses listed in §2.1, but **only the S1-relevant fields**. Other slices add fields incrementally; don't pre-populate the whole CE config surface.
- Implement `gsv/config/loader.py`:
  - YAML → dict via `pyyaml`.
  - `${VAR}` interpolation (raise on missing required vars; allow empty strings on optional).
  - Per-site override merge: `merge(visitor_dict, sites[site_name])` → flat `SiteConfig`.
  - `~` expansion on `storage_path` and `sessions_dir`.
- Tests: `tests/config/test_loader.py` covers env interpolation, missing-site error, override merge, defaults.
- **Do not** carry over CE's full ScraperConfig — only what `BrowserManager` reads. Other slices extend the model.

### Step 1.3 — Primitives + rate limiter

- Copy lines 22–198 + 43–69 from CE `browser.py` into `gsv/browser/primitives.py` and `gsv/browser/rate_limit.py`.
- Mechanical changes only: drop the `from src.config import ScraperConfig` import; preserve `# noqa: S311` markers.
- Add `tests/browser/test_primitives.py` and `tests/browser/test_rate_limit.py`.
- Determinism: every test injects a seeded `random.Random` via monkey-patching `random.uniform`/`random.randint`/`random.random` — or, preferably, factor the CE helpers to accept an optional `rng: random.Random | None = None`. **Recommendation:** factor RNG injection now; the per-slice cost is small, and S8 requires the same seam. (Open question Q2 below.)

### Step 1.4 — Fingerprint helpers

- Extract `_build_user_agent` and `_build_viewport` from CE `BrowserManager` into `gsv/browser/fingerprint.py` as pure functions.
- Signatures:
  ```python
  def build_user_agent(browser_version: str, platform: str = sys.platform) -> str: ...
  def build_viewport(rng: random.Random, width_range: tuple[int, int], height_range: tuple[int, int]) -> ViewportSize: ...
  ```
- Tests cover platform branches (`darwin`, `linux`, others), `browser_version` parsing (full `1.2.3.4`, major-only, empty), and viewport range bounds.

### Step 1.5 — BrowserManager

- Port lines 201–215, 247–337, 502–541 from CE `browser.py` into `gsv/browser/manager.py` (skipping the tracing/HAR/video methods reserved for S5).
- The HAR filter is the load-bearing generalization:
  ```python
  if har_path:
      kwargs["record_har_path"] = har_path
      if site.allowed_host_globs:
          kwargs["record_har_url_filter"] = site.allowed_host_globs[0]   # or a list — see Q1
  ```
  In S1 we never enter this branch (HAR is S5), but the code path must already accept the site config so S5 doesn't need to refactor `_build_context_kwargs`.
- `BrowserManager.__init__(visitor_config, site_config)` — explicit two-argument constructor. No global config singleton.
- `start()`: Chromium launch with `STEALTH_LAUNCH_ARGS`; load `storage_state` from `<site.storage_path>/state.json` if present; create context via `_build_context_kwargs(storage_state)`; `_apply_context_defaults()` (init script + default timeout).
- `save_session()`, `new_page()`, `close()`: copy verbatim (with the storage-path generalization).
- Tests: `tests/browser/test_manager.py` exercises start → new_page → goto fixture page → save_session → close → restart → confirm storage_state was loaded (look for the saved cookie). Use `chromium.launch(headless=True)` against the fixture server.

### Step 1.6 — Fixture HTTP server

- Add `tests/fixtures/server.py`: minimal async HTTP server serving:
  - `/` — basic HTML with a form (used by S2/S4)
  - `/dwell-test` — long page with scrollable content (used by S3 dwell tests)
  - `/cookie-set` — sets a cookie (used by S1 storage tests)
- Provide a pytest fixture `fixture_server_url` that starts the server on a random port and tears down afterward.
- This fixture is reused by S2, S3, S4. S1 only adds the minimum endpoints it needs.

### Step 1.7 — Public API and exports

- `src/gsv/browser/__init__.py` re-exports the public names: `BrowserManager`, `RateLimiter`, `random_delay`, `human_delay`, `random_mouse_move`, `click_with_position_jitter`, `run_humanized_page_dwell`, `human_type`, `scroll_page`, `STEALTH_LAUNCH_ARGS`, `WEBDRIVER_INIT_SCRIPT`, `ViewportSize`.
- `src/gsv/__init__.py` exports `__version__` (read from `pyproject.toml`) but does NOT re-export `gsv.browser` — keep imports explicit.

### Step 1.8 — Documentation

- Add `src/gsv/browser/README.md` (one-pager): module purpose, public API, how the primitives compose, link back to [ARCHITECTURE.md §4.1](../ARCHITECTURE.md#41-browser--fingerprint-layer-gsvbrowser).
- Update [IMPLEMENTATION_PLAN.md §3](../IMPLEMENTATION_PLAN.md#3-slice-index) checkbox once shipped.

---

## 5. Acceptance criteria

- [ ] `pytest tests/browser tests/config tests/test_smoke.py` is green on Python 3.10, 3.11, 3.12.
- [ ] Coverage for new modules ≥ 90%.
- [ ] `mypy src/gsv` passes (strict).
- [ ] `ruff` / `flake8` passes per existing pre-commit config.
- [ ] An integration test (`tests/browser/test_manager.py::test_storage_state_round_trip`) opens a real headless Chromium, sets a cookie via the fixture server, saves storage, reopens, and observes the cookie.
- [ ] No file under `src/gsv/` imports from `src.scraper.*` or `src.config`.
- [ ] No selectors, URLs, or strings containing `linkedin` exist in `src/gsv/` after the slice ships.
- [ ] `RateLimiter` blocks deterministically when saturated: a parameterized test with `max_per_hour=2` confirms the third `acquire()` waits.

---

## 6. Out of scope (deferred to later slices)

- Tracing / HAR / video lifecycle (`start_tracing`, `enable_har_for_session`, `finalize_har`, `finalize_video`) — **S5**.
- Session directory creation (`init_session`, `session_dir`, `session_id`, `cleanup_session_artifacts_on_success`) — **S5**.
- Login state machine, `Session` class, `ChallengePolicy` — **S2**.
- `DelayProfile`, `BurstGovernor`, `ContentAwareWait` — **S3**. S1 ships only the *raw primitives* the profile layer composes.
- Visit runner, step library — **S4**.
- CLI — **S6**.

If a CE method falls into a deferred slice, do not stub it in S1. The next slice will introduce its own seam.

---

## 7. Dependencies

- Upstream: none. S1 is the foundation.
- Downstream blockers: S2, S3, S4, S5 all import from `gsv.browser` and `gsv.config`.

---

## 8. Open questions

| ID | Question | Recommendation | Resolve in |
|---|---|---|---|
| Q1 | `record_har_url_filter` accepts a single glob in CE. If the new `allowed_host_globs` is a list, do we pick the first or build a regex union? | Resolved: S1 keeps the S5-ready hook and uses the first configured host glob when HAR kwargs are requested. | S1 |
| Q2 | Should primitives accept an explicit `rng: Random` argument now, or wait until tests bite? | Resolved: browser primitives and viewport construction accept injected `random.Random` instances. | S1 |
| Q3 | Should `BrowserManager` own its own `RateLimiter` or accept one injected? | Resolved: `BrowserManager` owns the limiter from `visitor.pacing.rate_limit_per_hour`; S7 can revisit shared limits if needed. | S1 |

---

## 9. Reviewer checklist (PR template)

- [ ] No CE-specific strings, URLs, or selectors in `src/gsv/`.
- [ ] HAR url filter is sourced from `site.allowed_host_globs`, not hardcoded.
- [ ] Locale and timezone defaults are `en-US` / `UTC`.
- [ ] Primitives accept (and tests use) seeded RNG.
- [ ] Fixture server is reusable (no `linkedin`-shaped routes).
- [ ] `tests/browser/test_manager.py` runs against headless Chromium in CI.
