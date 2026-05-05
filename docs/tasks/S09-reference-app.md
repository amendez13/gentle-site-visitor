# S9 — Reference app

> **Slice:** S9 of 10. See [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md).
> **Architecture refs:** [ARCHITECTURE.md §3](../ARCHITECTURE.md#3-layered-architecture), [ARCHITECTURE.md §10](../ARCHITECTURE.md#10-extending-the-skeleton-app-author-checklist).
> **Status:** Implemented for issue #21. **Depends on S1–S8.**

---

## 1. Goal

Prove the framework end-to-end by building one real app outside `src/gsv/`. The app must exercise every layer of the stack — `SiteAuthAdapter`, `VisitPlan`, `BrowserManager`, `Pacing`, `SessionRecorder`, `RunController`, `SchedulingRunner` — without adding a single line of framework code. Anything missing or awkward gets surfaced as a follow-up; we deliberately do not reach into `gsv/` to "fix" smells discovered here. Those are S10 inputs.

The reference app's job is **not** to scrape anything valuable — it is to be a stable, public, low-stakes target that future contributors can run end-to-end without credentials or rate-limit anxiety. We pick a site that is allowed to be visited by automated clients (e.g. its `robots.txt` is permissive, terms of service do not prohibit bot access) so that the example continues working without raising ethical or legal concerns.

After this slice, a developer should be able to:

```bash
git clone <repo> gsv && cd gsv
make install
gsv config validate --site example
gsv run example --once --observability=always
gsv sessions list --site example
gsv sessions inspect --site example --latest
gsv plan show --site example --date 2026-05-04 --seed 42
gsv worker --site example --schedule
```

…and watch a real `manifest.json`, optionally a `trace.zip` and `network.har`, land under `~/.local/state/gsv/sessions/example/<run-id>/`.

---

## 2. Target site selection

### 2.1 Constraints

The site must:

1. Be public and stable (low selector drift).
2. Permit automated access in `robots.txt` and ToS, OR be a site we own (a fixture).
3. Have *some* dynamic content so `WaitFor`, hydration retry, and `Extract` are exercised — a static HTML brochure site under-tests the runner.
4. Not require login (ideally) so contributors can run the example without secrets. If login is required, the credentials must be free to obtain and the auth flow non-CAPTCHA.
5. Have *enough* per-page work that a `BurstGovernor` cooldown actually fires within one run (i.e. ≥ N+1 actions per visit).

### 2.2 Recommendation

**Default: a public docs/blog site that the project itself controls** (a static site we deploy alongside the repo, e.g. a GitHub Pages site under the project's org), instrumented with light client-side rendering so hydration matters. This avoids the "what if the site changes its terms" risk and gives us a guaranteed-stable test target for CI.

**Alternative: Wikipedia.** Permissive crawler policy, well-documented selectors, dynamic content (search suggestions, infobox lazy-load on mobile), no login. The downside is that Wikipedia explicitly asks crawlers to use their dump or API for bulk traffic; one-shot interactive visits at human cadence are within their policy but we should document that the example is rate-capped and never run in batch mode.

The slice picks one and commits. Whichever target is chosen, [`apps/example/README.md`](#7-deliverables) documents the choice, the policy citation, and the rate cap.

### 2.3 What the visit does

A representative visit plan that exercises every step type:

1. `Navigate` to a landing page.
2. `WaitFor` a hydrated content marker (proves `ContentAwareWait`).
3. `Extract` the page title and a structured field (e.g. an article's first paragraph).
4. `Type` a query into a search box.
5. `Click` the search submit, with click-position jitter.
6. `WaitFor` the results list (hydration retry territory).
7. `ForEach` over the first three results: `Click`, `Extract`, `Branch` (visit detail iff a marker is present), back to list with `Navigate`.
8. `Scroll` to the page foot to trigger any lazy-load (proves `scroll_page`).
9. `Dwell` for a humanized closing read.
10. `RecordEvent("visit_complete")`.

This sequence guarantees: ≥ 1 navigation, ≥ 1 typed input, ≥ 1 click, ≥ 1 scroll, ≥ 1 extract, ≥ 1 branch, a `ForEach` (so hydration-retry counters are populated), and enough actions for the burst governor to cooldown at least once.

---

## 3. Deliverables

### 3.1 New files

```
apps/
  example/
    __init__.py
    auth.py           # SiteAuthAdapter — degenerate "no-auth" implementation
    selectors.py      # Centralized CSS / role selectors used by visit.py
    visit.py          # build_plan() -> VisitPlan factory
    extractors.py     # Pure functions called by Extract steps
    config.yaml       # Site config (timezone, locale, allowed_host_globs, schedule profiles)
    README.md         # What it does, why this site, how to run, expected output
    smoke_test.py     # Optional: a one-shot script that runs `gsv run example --once` and asserts on the resulting manifest
tests/
  apps/
    example/
      __init__.py
      test_visit_plan_offline.py   # Plan factory produces a well-formed VisitPlan; no network
      test_extractors.py           # Pure-function extractor tests
      test_selectors_freshness.py  # Marker test that fails on next selector audit cadence (informational)
```

### 3.2 Modules to update (framework — minimal!)

The S9 slice **must not** modify any module under `src/gsv/`. If a real need surfaces (e.g. a hook the framework didn't expose), record it under [§ 6 Discoveries](#6-discoveries-feeds-s10) and defer to S10.

The only allowed touches outside `apps/example/`:

| Path | Change |
|---|---|
| `src/gsv/cli/run.py` | If and only if the `--site` lookup needs to be taught about the new app: add a registration mechanism (entry-point or static dict). Most likely already handled in S6. |
| `pyproject.toml` | Register an `apps.example` entry point if S6 chose entry-point discovery. |

If both are no-ops, S9 ships as a pure additive: `apps/example/**` and `tests/apps/example/**` only.

### 3.3 Tests

Three testing surfaces, each with a different blast radius:

**Offline plan tests** (`tests/apps/example/test_visit_plan_offline.py`):
- `build_plan()` returns a `VisitPlan` with the expected step sequence and labels.
- Selector references resolve to non-empty strings (catches typos).
- No `gsv.browser` or Playwright import is required to run these tests.

**Extractor unit tests** (`tests/apps/example/test_extractors.py`):
- Feed each extractor a sample HTML fragment (`tests/apps/example/fixtures/*.html`) and assert the structured output.
- These are pure-function tests; no browser, no fixtures server.

**Smoke test** (`apps/example/smoke_test.py`):
- Not a unit test — a runnable script that calls `gsv run example --once --observability=always` and asserts:
  - exit code 0,
  - `manifest.json` has `result == "success"` and at least one `actions_total > 0`,
  - `evidence.jsonl` contains at least the events emitted by `RecordEvent` steps in the plan.
- Documented as opt-in (`make smoke-test-example`) and **not** part of the default `pytest` run because it requires real network.

---

## 4. Step-by-step

### Step 9.1 — Pick the target

Open a discussion in the slice's PR description: list candidate sites, paste their `robots.txt` for each, link to ToS sections that bear on automated access, and converge on one. Document the choice in [`apps/example/README.md`](#7-readme-template).

### Step 9.2 — Adapter

`apps/example/auth.py`:

```python
from gsv.session import SiteAuthAdapter
from gsv.session.policy import ChallengePolicy

EXAMPLE_AUTH_ADAPTER = SiteAuthAdapter(
    site_name="example",
    login_url=None,                        # No-auth target; if login is needed, fill in
    home_url="https://example.com/",
    auth_marker_selector="header nav",     # Element that proves "logged in" (or just "loaded")
    username_selectors=(),
    password_selectors=(),
    submit_selectors=(),
    completion_selectors=("header nav",),
    challenge_policy=ChallengePolicy.HEADED_WAIT,
)
```

For a no-auth target, the adapter still exists — it just degenerates to a `home_url` + `auth_marker_selector` pair. `gsv.session.Session` short-circuits when there are no credential selectors (this seam is added in S2; if S2 didn't include it, this slice's review surfaces it as an S10 follow-up).

### Step 9.3 — Selectors

`apps/example/selectors.py`:

```python
SEARCH_INPUT = "input[type='search']"
SEARCH_SUBMIT = "button[type='submit']"
RESULTS_LIST = "[data-testid='results']"
RESULT_ITEM = "[data-testid='result-item']"
ARTICLE_TITLE = "h1"
ARTICLE_FIRST_PARA = "article p:first-of-type"
PAGE_FOOTER = "footer"
```

All selectors live in this one module so future audits target a single file. The `test_selectors_freshness.py` test simply imports them and asserts the module exposes the expected names — it doesn't visit the site (we don't want CI dependent on a real third-party).

### Step 9.4 — Plan factory

`apps/example/visit.py`:

```python
from gsv.visit import VisitPlan
from gsv.visit.steps import (
    Navigate, WaitFor, Extract, Type, Click, Scroll, Dwell,
    ForEach, Branch, RecordEvent,
)
from . import selectors as S
from . import extractors as E

def build_plan(*, query: str = "gentle visitor") -> VisitPlan:
    return VisitPlan(
        site="example",
        steps=[
            Navigate(url="https://example.com/"),
            WaitFor(selector=S.PAGE_FOOTER, label="landing_loaded"),
            Extract(name="landing_title", fn=E.extract_title),
            Type(selector=S.SEARCH_INPUT, text=query),
            Click(selector=S.SEARCH_SUBMIT, label="submit_search"),
            WaitFor(selector=S.RESULTS_LIST, label="results_hydrated"),
            ForEach(
                selector=S.RESULT_ITEM,
                limit=3,
                inner=[
                    Click(selector="a", label="open_result"),
                    WaitFor(selector=S.ARTICLE_TITLE, label="article_loaded"),
                    Extract(name="article_title", fn=E.extract_title),
                    Branch(
                        if_selector=S.ARTICLE_FIRST_PARA,
                        then_=[Extract(name="article_summary", fn=E.extract_summary)],
                        else_=[RecordEvent("article_skeleton_only")],
                    ),
                    Navigate(url="back"),
                    WaitFor(selector=S.RESULTS_LIST, label="results_rehydrated"),
                ],
            ),
            Scroll(direction="end", label="scroll_to_footer"),
            Dwell(label="closing_read"),
            RecordEvent("visit_complete"),
        ],
    )
```

The plan is parameterized only by `query`. Other parameters (URL bases, depth) are hardcoded — apps own their parameter surface, they don't need to be CLI-flag-tunable.

### Step 9.5 — Extractors

`apps/example/extractors.py`:

```python
from playwright.async_api import Page

async def extract_title(page: Page) -> str:
    el = await page.locator("h1").first.text_content()
    return (el or "").strip()

async def extract_summary(page: Page) -> str:
    el = await page.locator("article p:first-of-type").first.text_content()
    return (el or "").strip()
```

Extractors are pure-ish: they take a `Page`, return data. They do **not** call `BrowserManager` primitives directly (no humanization here — that's the runner's job around the step).

### Step 9.6 — Config

`apps/example/config.yaml`:

```yaml
visitor:
  state_dir: ~/.local/state/gsv
  observability:
    mode: failures           # off | failures | always
    retention_days: 14
    retention_max_count: 100
  pacing:
    delay_profile: production
    burst:
      every_n: 12
      cooldown_min_seconds: 45
      cooldown_max_seconds: 120
  schedule:
    activity_window_start: "08:00"
    activity_window_end: "22:00"
    rest_min_minutes: 30
    rest_max_minutes: 90
    profiles:
      - id: example_morning
        name: Morning visit
        frequency: weekdays
        preferred_time: "09:30"
        jitter_minutes: 30
      - id: example_afternoon
        name: Afternoon visit
        frequency: weekdays
        preferred_time: "16:00"
        jitter_minutes: 45

sites:
  example:
    auth_adapter: apps.example.auth:EXAMPLE_AUTH_ADAPTER
    plan_factory: apps.example.visit:build_plan
    locale: en-US
    timezone: UTC
    allowed_host_globs:
      - "*.example.com"
      - "example.com"
    rate_limit:
      requests_per_hour: 60   # Polite cap; well below the site's published limits
```

Interpolation, validation rules, and per-site override semantics are defined in S1 / S6 — S9 only consumes them.

### Step 9.7 — Smoke test

`apps/example/smoke_test.py` is a runnable Python script (not pytest), invoked via `make smoke-test-example`. It runs `gsv run example --once --observability=always`, then opens the produced manifest and asserts:

- `result == "success"` (or `partial` if cancellation tests are added),
- `counters["actions_total"] >= len(plan.steps)`,
- `counters["cooldowns"] >= 1` (proves burst governor fired),
- `evidence.jsonl` contains a record with `event == "visit_complete"`.

The script exits non-zero on any assertion failure. It is run by hand, not by CI (network-dependent).

### Step 9.8 — Documentation

`apps/example/README.md` includes:

1. **What this is.** "A reference app demonstrating Gentle Site Visitor against `<chosen site>`."
2. **Why this site.** Citation of the site's `robots.txt` / ToS, plus a one-paragraph rationale.
3. **How to run.** `gsv config validate --site example`, `gsv run example --once`, `gsv sessions inspect --latest`.
4. **Expected output.** Sample manifest snippet, list of evidence events, expected counter values.
5. **Adapting this for your own site.** Pointer to [ARCHITECTURE.md §10](../ARCHITECTURE.md#10-extending-the-skeleton-app-author-checklist).

### Step 9.9 — End-to-end smoke

Before merging:

1. `gsv config validate --site example` → exits 0.
2. `gsv run example --once --headed --observability=always` → exits 0; manifest written.
3. `gsv plan show --site example --date <today> --seed 42` → prints a stable table.
4. `gsv worker --site example --schedule` → fires at least one slot; Ctrl-C exits cleanly.
5. `gsv sessions list --site example` → shows the run from step 2.

Capture the terminal output of each into the PR description so reviewers can see the demo without re-running it.

---

## 5. Acceptance criteria

- [ ] `apps/example/` contains exactly the seven files listed in [§ 3.1](#31-new-files); no others.
- [ ] No file under `src/gsv/` is modified by this slice (or, if one is, the change is flagged as a framework gap and reviewed against the "minimal touches" rule).
- [ ] `pytest tests/apps/example/` is green and runs without network.
- [ ] `make smoke-test-example` succeeds against the live site at least once at PR review time (output captured in PR description).
- [ ] `apps/example/config.yaml` validates under `gsv config validate`.
- [ ] `apps/example/README.md` cites the site's automation policy and the polite rate cap.
- [ ] `gsv run example --once --observability=always` produces a `manifest.json` whose `counters` dict contains, at minimum: `actions_total`, `cooldowns`, `hydration_retries`, `cancellation_boundary` (zero for a successful run).

---

## 6. Discoveries (feeds S10)

This section is *expected* to be filled in during the slice. Anything that surprised the author goes here, not into framework patches:

| Symptom | Where felt | Likely framework gap | Defer to S10? |
|---|---|---|---|
| _e.g._ "had to write my own back-navigation helper because `Navigate(url='back')` doesn't exist" | `apps/example/visit.py` step 7 | Add `Back` step or accept `'back'` as `Navigate.url` value | yes |
| The app owns a concrete `WIKIPEDIA_AUTH_ADAPTER`, but current runtime setup builds adapters from YAML only. | `apps/example/auth.py` and `apps/example/config.yaml` | Consider first-class app-provided auth adapter resolution or remove the adapter-file requirement from future app contracts. | yes |
| Evidence rows are written as `{event_type, payload}` while older task text expected an `event` field. | `apps/example/README.md` and PR smoke output | Align the app-author docs and smoke-test examples with the S5 evidence sink schema. | yes |
| The S9 smoke contract expects `actions_total` and `cancellation_boundary`, but the runner naturally emits `requests_made`, `cooldowns`, and hydration counters. | `apps/example/visit.py` | Decide whether these normalized counters belong in the framework runner instead of each app. | yes |
| Enabling both trace and HAR caused trace finalization to warn after HAR recreated the browser context. | Live smoke with `--observability=always` | Preserve trace state across HAR context rotation or document trace/HAR interaction. | yes |
| No new gaps found requiring framework code changes in this PR. | S9 implementation | Keep S10 focused on documentation/schema polish for the app contract findings above. | no |

Each row of this table that resolves to "yes, defer" becomes an S10 deliverable.

---

## 7. README template

The minimal `apps/example/README.md` skeleton:

```markdown
# Example app

Reference Gentle Site Visitor app demonstrating an end-to-end gentle visit
against `<chosen site>`.

## What it does

<one paragraph on the visit>

## Why this site

`<chosen site>` permits automated access (see <link to robots.txt>) and is
stable enough to use as a demo target. We rate-limit ourselves to 60 visits
per hour, well below their published limits.

## Running

    gsv config validate --site example
    gsv run example --once --headed --observability=always
    gsv sessions inspect --site example --latest

## Expected output

- `manifest.json` with `result: success`, `counters.actions_total >= 11`.
- `evidence.jsonl` contains an event `{ "event": "visit_complete" }`.
- `network.har` (only with `--observability=always`).

## Adapting for your own site

See [ARCHITECTURE.md §10](../../docs/ARCHITECTURE.md#10-extending-the-skeleton-app-author-checklist).
```

---

## 8. Out of scope (deferred)

- Multiple example apps (one is enough to prove the contract; future apps live outside this repo).
- A "headless CI smoke test" against the live site — too brittle. Hand-run before each release.
- Visual regression / screenshot tests — `apps/example/` is not a UI test framework.
- Logged-in flows — the reference app is deliberately no-auth so contributors don't need credentials.

---

## 9. Dependencies

- Upstream: **S1–S8** (every layer must already exist).
- Downstream blockers: **S10** (hardening uses the discoveries from this slice as input).

---

## 10. Open questions

| ID | Question | Recommendation | Resolve in |
|---|---|---|---|
| Q1 | Live site or owned fixture? | Owned static site (deployed via GitHub Pages) when possible; Wikipedia as a fallback. | S9 |
| Q2 | Should the smoke test be wired into CI? | No — network-dependent and brittle. Run locally before release; capture output in PR description. | S9 |
| Q3 | Do we need a `Back` navigation step, or is `Navigate(url='back')` enough? | Decide during plan implementation; if both are awkward, file under § 6. | S9 |
| Q4 | Should `apps/example/` register itself via entry points, or is a static dict in S6's CLI enough? | Static dict for now. Entry points only if a second app appears. | S9 (revisit S10) |

---

## 11. Reviewer checklist

- [ ] No `linkedin`, `feed`, `job`, `company`, or `vps` strings under `apps/example/`.
- [ ] No imports from `src.scraper.*` or `careerexplorer.*` anywhere.
- [ ] No code under `src/gsv/` was modified (or, if one file was, it's flagged in the PR description with a one-paragraph justification).
- [ ] `apps/example/README.md` cites the site's `robots.txt` line that permits automation.
- [ ] `apps/example/config.yaml` is the only file with environment-specific paths (no `~/.local/...` hardcoded inside `apps/example/*.py`).
- [ ] PR description includes captured output of the five end-to-end smoke commands from [§ 4.9](#step-99--end-to-end-smoke).
- [ ] § 6 Discoveries is populated, even if "no new gaps found" is the only entry.
