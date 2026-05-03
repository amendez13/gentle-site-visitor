# Gentle Site Visitor — Research Findings (scratch)

> Working notes extracted from CareerExplorer. Reorganize into `docs/ARCHITECTURE.md` after research is complete. This file is intentionally messy and chronological.

## Research scope

Pull out generic, reusable patterns for:
- Authenticated, real-looking Playwright sessions
- Anti-bot evasion (fingerprint, headers, IP/network choices)
- Human-like interaction (delays, jitter, mouse movement, scrolling, typing cadence)
- Gentle pacing (request rate, backoff, schedule windows)
- Session lifecycle (warmup, cookie persistence, expiry detection, re-auth)
- Operational coupling (scheduler, worker, telemetry, retry, cancellation)

Discard CareerExplorer-specific concerns:
- Job/company schema, LinkedIn-specific endpoints, enrichment pipelines, matcher, ops dashboard, canonical Postgres, job intelligence

## Files to investigate

Docs (priority order):
- `docs/LINKEDIN.md` — likely the densest source on real-site behavior
- `docs/ARCHITECTURE.md` — already read, captures task/worker model
- `docs/AGENT_CONTEXT.md` — agent-level context for gentle behavior
- `docs/WORKER_SETUP.md`, `docs/NUC_SETUP.md` — runtime/network environment
- `docs/ORCHESTRATOR_RUNBOOK.md` — pacing/scheduling

Source (priority order):
- `src/scraper/browser.py` — Playwright launch/context, fingerprint, stealth
- `src/scraper/auth.py` — login flows, cookie persistence
- `src/sessions.py` — session lifecycle / persistence
- `src/scraper/jobs.py`, `src/scraper/companies.py` — interaction patterns
- `src/linkedin_pagination.py` — pacing/backoff per page
- `src/worker.py` — leasing, heartbeat, cancellation cooperation
- `src/orchestrator_plan.py`, `src/orchestrator.py` — scheduling windows

---

## Findings (running log)

### F1. `docs/LINKEDIN.md` — anti-bot / human-like inventory

This document is the densest single source. The scraper's rate-limit / realism stack:

**Pacing**
- Rate limiter with configurable `max_requests_per_hour` (default 90)
- Production interaction delay: random `min_delay`..`max_delay` (default 2-5s)
- Faster "panel_probe" debug delay range (0.8-1.8s)
- Humanized cadence profile with occasional **long distraction waits**
- Periodic **burst cooldown** pauses after a configurable interval of detail-page visits
- Per-page content-aware wait: after `goto()`, wait for key selectors **then** add a small reaction delay before acting

**Browser fingerprint hardening**
- Chromium launch args: `--disable-blink-features=AutomationControlled`, etc.
- UA generated from actual Playwright Chromium version (no stale static UA)
- `navigator.webdriver` patched to `undefined` via init script
- Configurable `locale`, `timezone_id`
- Per-session randomized viewport within a normal laptop range (1260-1380 x 780-900)

**Interaction realism**
- Simulated cursor movement between major actions (login, pagination, detail, company)
- Clicks use in-element position **jitter** instead of fixed-center
- Scroll simulation to trigger lazy-loaded content
- Post-extraction "dwell": scroll down/up + dwell time on both detail and company pages
- Hydration-aware card parsing (non-viable card → scroll into view + short wait + retry once)

**Session lifecycle**
- Cookie/session persistence via `storage_state` JSON file (`data/linkedin_session/state.json`)
- Post-auth warmup: browse/scroll the feed briefly after restoring or fresh-login, before starting work
- Warmup skipped in `--once` runs for debug cycles
- Login expiry detected on auth check; auto re-login with credentials
- 2FA/challenge: headed waits up to `manual_verification_timeout` (default 300s); headless fails fast
- Login form variants handled (account-chooser vs classic), cookie-consent click first
- Fallback credential / submit selectors

**Operational gentleness**
- Residential IP requirement (worker runs from home network, not datacenter)
- Quality gate: too-low extraction quality fails the task instead of submitting bad data
- Pre-check duplicates against server before detail extraction (saves real visits)
- Selector telemetry (primary hit / fallback hit / miss) per field
- Hard pagination cap (LinkedIn's ~1000-result offset) enforced as defense-in-depth

**Debug-only modes (worth abstracting)**
- `panel_probe` mode: link-only probe with no detail extraction (gentle reconnaissance)
- `integrity_audit` (sample / full / disabled) with explicit "increases detection risk" warning and a `max_extra_requests_per_task` hard cap
- Debug artifacts: per-failure screenshot + HTML dump under `<session>/debug_artifacts/`

### Generic primitives this doc surfaces (to extract)

1. **Rate limiter** with hourly cap
2. **Delay profile** abstraction with named ranges (`production`, `probe`, custom) and occasional-long-wait sampling
3. **Burst cooldown** governor (every N actions → longer pause)
4. **Content-aware wait** + post-content reaction delay
5. **Browser fingerprint profile**: launch args, dynamic UA, `navigator.webdriver` patch, locale/timezone, randomized viewport
6. **Interaction primitives**: cursor pathing, click-with-jitter, scroll simulation, dwell helper
7. **Session bundle**: `storage_state` JSON + auth detection + auto re-login + 2FA escalation policy
8. **Login flow abstraction**: cookie-consent first, variant detection, selector fallback chain
9. **Warmup hook**: pre-work feed browsing
10. **Quality gate** at task boundary
11. **Selector registry with fallback chain + telemetry**
12. **Debug-only safe-mode probes** (per-card / link-only / integrity)

### F2. `src/scraper/browser.py` — concrete primitives

Already self-contained, mostly site-agnostic. Lifts directly:

```
STEALTH_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-component-update",
]
WEBDRIVER_INIT_SCRIPT = "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
```

**Primitives (all generic, lift as-is)**

- `RateLimiter`: monotonic-clock sliding window of timestamps, awaits next slot when full
- `random_delay(min_s, max_s)` — uniform random sleep
- `human_delay(min_s, max_s, distraction_chance, distraction_min_s, distraction_max_s)` — same with ~10% chance of long "distraction" sleep (15-45s default)
- `random_mouse_move(page)` — moves mouse to a random in-viewport position with `steps=random.randint(5,15)`, viewport-padded; resolves viewport from `page.viewport_size` or `window.innerWidth/Height`
- `click_with_position_jitter(page, selector)` — bounding box → uniform 30-70% jitter inside the element, mouse-move with `steps=4-12`, then click; falls back to `page.click()` on failure
- `run_humanized_page_dwell(page, min_seconds, max_seconds)` — randomizes a target (~7-10s), splits into down-scroll budget (55-70%) and up-scroll budget (20-35%), with `scrollBy` deltas of 140-420px down and 100-300px up, mouse moves between scroll bursts
- `human_type(page, selector, text)` — mouse-move → jitter-click → fill empty → per-char `page.type` with `delay=50-150ms` → trailing 0.3-0.8s pause
- `scroll_page(page, times)` — full-viewport scroll with mouse moves between

**`BrowserManager` capabilities (split into "core" vs "observability")**

Core (must lift to skeleton):
- Launch Chromium with `STEALTH_LAUNCH_ARGS`, headless toggle
- `_build_user_agent`: regex parse `browser.version` to align UA Chrome/x.x.x.x with the actual Playwright Chromium; platform token from `sys.platform` (darwin/linux/windows)
- `_build_viewport`: random 1260-1380 x 780-900 per session
- `_build_context_kwargs`: viewport + locale + timezone_id + user_agent + storage_state
- `_apply_context_defaults`: `add_init_script(WEBDRIVER_INIT_SCRIPT)` + `set_default_timeout(page_timeout * 1000)`
- `start()`: load `storage_state` from `<session_path>/state.json` if present
- `save_session()`: writes `state.json` from `context.storage_state()`
- `new_page()`: rate-limiter-gated context.new_page

Observability (powerful, lift as opt-in):
- Per-task session directory: `<sessions_dir>/<UTC-stamp>_task-<id>/`
- Playwright `tracing.start(screenshots=True, snapshots=True, sources=False)` → `trace.zip` in session dir
- HAR recording (`record_har_path`, `record_har_url_filter`, `record_har_content`)
- Video recording (`record_video_dir`, `record_video_size=1280x800`)
- Important: HAR/video must be configured at context-creation time → `enable_har_for_session()` rotates the context (saves storage state, closes old, opens new with recording, reapplies init scripts)
- `finalize_har`/`finalize_video`: rotate context back, promote `*.webm` to canonical names
- `cleanup_artifacts_on_success`: in `mode=failures`, delete heavy artifacts on success

**Generalization notes**
- `record_har_url_filter` is hard-coded to `**/*linkedin.com/**` — must become a config option (allow-list of host patterns).
- The 1280x800 video size and 1260-1380 / 780-900 viewport ranges should be configurable presets, not constants.

### F3. `src/scraper/auth.py` — generic auth flow shape

Strip LinkedIn URL constants and selector lists; the SHAPE is:

1. `start()`: launch browser → check authenticated state by visiting a "logged-in marker URL" → set `_authenticated`
2. `_check_authenticated()`: navigate to a "post-auth marker URL", short delay, classify by URL (positive marker / negative marker)
3. `login(email, password)`:
   - Navigate to login URL
   - Try cookie-consent click first (selector list)
   - Detect login-page variant (e.g., account-chooser) and click variant trigger
   - Fill credentials with **selector fallback chain** for username, password, submit
   - All inputs use `human_type` (jittered click + per-char typing delay)
   - Random delay between fills, random mouse moves between fills
   - Wait for post-login navigation; if URL ends up on `verification`/`challenge`:
     - Headed: poll `_is_feed_url(page.url)` for up to `manual_verification_timeout` seconds (1s tick)
     - Headless: log warning and fail
   - Save session on success
4. `post_login_warmup()`: optional one-shot feed browse + scroll to imitate post-auth user behavior; runs once per session, gated on config flag, skipped on first run
5. Diagnostics-on-failure: log URL, title, and per-selector locator counts so failed login can be triaged from logs alone

This is **dead-generic**. It's a state-machine over URL patterns with three pluggable selector groups (cookie-consent / account-chooser / credentials/submit) and one positive-feed-marker URL test.

### F4. `src/sessions.py` — session artifact / observability operations

Site-agnostic. The model is:

- Each task run gets a session directory `<sessions_dir>/<YYYY-MM-DDThhmmssZ>_task-<id>/`
- Inside: `manifest.json`, optional `trace.zip`, `network.har`, `video.webm`, log artifacts
- Manifest fields: `task` (with `id`, `search_query`), `outcome`, `duration_seconds`, `results` (with counters), `artifacts` (dict of artifact-name → path), `error`
- Retention: by `--older-than N days` and/or `--keep N most recent`
- CLI commands: `list` (table or JSON), `open` (Playwright Trace Viewer via `npx playwright show-trace`), `inspect` (pretty-print manifest), `purge`
- Default retention: 14 days, max 100 sessions

This is a clean, lift-as-is observability layer. Even the prefix-matching for session IDs in `open`/`inspect` is generic enough to keep verbatim. Generalization: rename `task` → `run` or `visit` so the schema is not coupled to "task".

### F5. `src/config.py` — config surface for gentle behavior

The relevant dataclasses to lift, generalized:

```python
ObservabilityConfig:
    mode: "off" | "failures" | "always"  # default "failures"
    trace, har, video, structured_logs: bool
    sessions_dir: str = "data/sessions"
    retention_days: int = 14
    max_sessions: int = 100
    har_content: "omit" | "embed" = "omit"

ScraperConfig (rename → VisitorConfig or BrowserConfig):
    session_path: str       # storage_state directory
    headless: bool = True
    locale: str             # default es-ES, must be configurable per app
    timezone_id: str        # default Europe/Madrid → must be configurable
    min_delay, max_delay    # production action range, default 2-5s
    panel_probe_delay_range # secondary delay range (debug/probe)
    max_requests_per_hour: int = 90
    page_timeout: int = 30  # seconds
    manual_verification_timeout: int = 300  # seconds
    burst_cooldown_interval: int = 5        # actions per burst window
    burst_cooldown_range: [30.0, 90.0]      # cooldown sleep range
    post_login_warmup: bool = True
    observability: ObservabilityConfig
    integrity_audit: IntegrityAuditConfig    # generalize → safe_audit
    # max_pages and target_visited fields are LinkedIn search-specific; drop.
```

Worker-level fields that matter for gentle behavior in general:

```python
WorkerConfig:
    poll_interval: int = 300
    mode: "production" | "panel_probe"   # generalize → main mode + named recon modes
    lease_ttl_seconds: int = 120
    heartbeat_interval_seconds: int = 30
    incremental_submit:
        enabled: bool
        flush_every_n_jobs: int
        flush_every_seconds: int
```

Config loader does env-var interpolation `${VAR}` and `~`-expansion — useful for credentials.

### F6. `src/scraper/jobs.py` — usage patterns of the primitives

I did not need to read every line; the grep tells the integration story:

- After every `goto`, `wait_for_selector(content_marker, timeout=10000)` then `random_delay(0.5, 1.5)` then `random_mouse_move(page)` → **content-aware wait + reaction delay + idle mouse move**. This is the canonical post-navigation prelude.
- Between distinct pages of work: `random_delay(config.min_delay, config.max_delay)` + `scroll_page(page, times=2..3)` → **simulated lazy-load trigger**.
- For every clickable target: prefer `click_with_position_jitter` first, fall back to `page.click()` (`_try_click_element` toggle, `jitter_first` param).
- Every detail extraction ends with `run_humanized_page_dwell(page)` (scroll-down + scroll-up + dwell) — **read-time simulation**.
- Burst governor: `if cards_clicked % burst_interval == 0: cooldown = uniform(cooldown_min, cooldown_max); sleep(cooldown)` — every Nth action triggers a longer pause.
- Hydration retry: when first parse fails to find data, `card.scroll_into_view_if_needed(timeout=3000)` + `random_delay(0.05, 0.15)` + retry once.
- Panel probe / probe modes use `panel_probe_delay_range` (faster) instead of production delay range.

These usage patterns translate cleanly into a small set of "Visit Step" abstractions, see synthesis below.

### F7. Anti-bot stance summary (across the doc set)

CareerExplorer takes a **layered, defense-in-depth gentle stance**, NOT an "evade detection" stance. Worth quoting in the design doc — this is the philosophical anchor:

1. Network: residential IP (home network), not datacenter.
2. Browser: real Chromium build, not a stealth wrapper.
3. Fingerprint: aligned UA / locale / timezone / per-session viewport jitter.
4. Behavior: human-cadence delays, mouse pathing, click jitter, scroll, dwell, distraction sleeps, burst cooldowns.
5. Session: cookie persistence, post-auth warmup, manual-verification fallback.
6. Pacing: hourly request cap + per-action ranges + burst cooldown.
7. Quality gate: refuse to submit obviously bad data (failed extraction → fail the run instead of poisoning the dataset).
8. Auditability: per-task session bundle (manifest / trace / HAR / video) for forensic replay; retention policy.
9. Restraint: extra-request features (audits) are off by default and capped.
10. Rate awareness: stop pagination at known platform hard caps (e.g., LinkedIn 1000-offset).

This stance should drive the design doc's "principles" section.

### F8. `src/worker.py` — cooperative cancellation pattern

Lift verbatim, the abstractions are not job-specific:

```python
class TaskCancellationRequested(RuntimeError):
    # carries reason + partial payloads (jobs/companies/attempts)
    # for "drain on cancel" semantics

class TaskCancellationMonitor:
    # debounced poll wrapper:
    # - min_poll_interval_seconds (default 2.0)
    # - check(force, boundary) → polls server's task_control endpoint
    # - boundary string for telemetry (e.g., "search_progress")
    # - raises TaskCancellationRequested on cancel
```

Used at every "natural break" in the visit:
- `search_progress`, `search_panel_detail`, `search_page`
- `detail_fetch`, `detail_extraction`
- `before_inter_detail_delay`, `before_burst_cooldown`
- `before_company_duplicate_check`, `before_final_chunk_submit`
- `panel_probe_start`, `panel_probe_complete`

**Generic naming pattern**: `boundary` is `<phase>_<sub-phase>` and is included in cancellation logs. Worth keeping the convention; the boundaries are the natural async checkpoints in any visit DAG.

**Lease/heartbeat model** (also generic):
- Worker registers a lease (worker_id + lease_token) before claiming work
- Background `_lease_heartbeat_loop` sends periodic heartbeats
- Heartbeat backoff schedule: `(5, 15, 30)` seconds for transient failures
- Transient reasons (allow re-register): `lease_expired`, `lease_not_found`, `lease_not_active`, `transport_error`
- Terminal reason: `invalid_lease_token` (worker exits)
- Self-heal on claim: if claim fails with one of `_CLAIM_SELF_HEAL_REASONS`, re-register and retry
- Sleep chunk: `_HEARTBEAT_SLEEP_CHUNK_SECONDS = 15.0` (sleep between heartbeats but in 15s chunks so cancellation responds quickly)

**Worker exit codes**:
- 0 OK
- 1 runtime error
- 10 auth failure (login broken — needs operator)
- 20 config error

Useful semantic for systemd/launchd restart logic ("restart on runtime, fail fast on auth/config").

### F9. `src/orchestrator_plan.py` — macro-pacing layer

Pure planning, no IO. Generic primitives:

- **Activity window**: `activity_window_start`, `activity_window_end` (HH:MM, no cross-midnight). Day-of-week respected via `frequency` (e.g., `daily`, `mon,tue,wed,...`).
- **Per-slot jitter**: `compute_jittered_time(preferred_time, jitter_minutes, rng)` shifts each profile's slot by uniform ±N minutes. Critical for not running at literal HH:00 or HH:30.
- **Rest-period enforcement**: `enforce_rest_periods(slots, rest_min, rest_max, window_end, rng)` — pushes each subsequent slot forward by a random `rest_min..rest_max` minutes from the previous *kept* slot. Slots that overflow `window_end` get marked `skipped="outside_activity_window"`.
- Output: a sorted, jittered, rest-spaced `list[PlannedSlot]` per day.

This is exactly the macro-pacing primitive a Gentle Site Visitor needs to schedule batched visits over a day, avoiding suspicious clockwork timing and respecting quiet hours.

### F10. `src/linkedin_pagination.py` — platform-cap guardrail pattern

Tiny module, but the **shape** is reusable: a small constants-and-guards module per target site that:

- Declares hard limits (page size, max offset)
- Provides `compute_*` helpers
- Provides a deterministic, operator-facing error message builder

Generalize to per-site "platform constraints" modules (`sites/<name>/limits.py`), keeping the pattern but not LinkedIn's numbers.

---

## CareerExplorer-specific (DO NOT lift)

- LinkedIn URLs (`/login`, `/feed/`, `/jobs/search/`, `/jobs/view/`, `/company/`)
- LinkedIn `SELECTORS` dict and `_DETAIL_CRITERIA_SELECTORS`
- Job/company schemas, `_merge_job_data`, employment_type/seniority/salary fields
- `linkedin_filters` URL parameter mapping (`f_TPR`, `f_E`, `f_WT`)
- Company `/about/` extraction logic
- Pagination 1000-offset cap (replace with site-specific module)
- VPS API contract (search task model, job ingestion endpoints, company enrichment, ops dashboard)
- Canonical Postgres / intel / matcher / job_intelligence
- HAR url filter `**/*linkedin.com/**` (parameterize)
- Default `locale=es-ES` and `timezone_id=Europe/Madrid` (default to UTC; force config)
- `panel_probe` mode is LinkedIn-SPA-specific; the generic concept is **"recon-only mode"** that traverses the visit graph without performing destructive actions or full extraction

## Generic abstractions to deliver in `gentle-site-visitor`

Working list (will refine in design doc):

1. **`browser/`** — `BrowserManager`, fingerprint helpers, primitives (`random_delay`, `human_delay`, `random_mouse_move`, `click_with_position_jitter`, `human_type`, `scroll_page`, `run_humanized_page_dwell`), `RateLimiter`. Site-agnostic.
2. **`session/`** — generic auth-flow state machine + storage_state persistence + post-auth warmup hook + manual-verification escalation policy. Subclass per site.
3. **`pacing/`** — `DelayProfile` (named ranges + distraction probability), `BurstGovernor` (every-N-actions cooldown), `ContentAwareWait` (selector-then-reaction prelude). All composable.
4. **`scheduling/`** — port of `orchestrator_plan.py`: activity windows, per-slot jitter, rest-period enforcement.
5. **`observability/`** — port of `sessions.py`: per-run session directory, manifest schema, trace/HAR/video on context, retention CLI.
6. **`run/`** — `Run` (=task) lifecycle, lease/heartbeat client, cooperative cancellation (`CancellationMonitor` + `boundary` checkpoints), exit codes.
7. **`visit/`** — `VisitStep` interface (`navigate`, `interact`, `extract`, `dwell`) so apps assemble visits as DAGs/sequences of small steps and the framework injects pacing/observability around each.
8. **`sites/<name>/`** — adapters: per-site selectors, login flow specialization, allowed-host list for HAR, per-site rate limits and platform caps. Apps live here.
9. **`config/`** — pydantic/dataclass surface mirroring `ScraperConfig` minus LinkedIn-specific fields, with `${ENV}` interpolation and per-site override layer.
10. **`cli/`** — `gentle-visit run <site> <run_args>`, `gentle-visit sessions list/open/inspect/purge` (port of CLI), `gentle-visit plan show <date>`.
