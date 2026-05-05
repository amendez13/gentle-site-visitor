# Gentle Site Visitor — Implementation Plan

> **Status:** v0 implemented baseline — this document records how the architecture in [ARCHITECTURE.md](ARCHITECTURE.md) was delivered and where follow-up hardening work remains.
> **Audience:** maintainers and AI coding agents that will execute the slices below.
> **Companion docs:**
>
> - [ARCHITECTURE.md](ARCHITECTURE.md) — *what* we are building and *why*.
> - [notes/_findings.md](../notes/_findings.md) — raw research notes from CareerExplorer extraction.

---

## 1. Purpose and scope

This plan turns the Gentle Site Visitor architecture into an ordered, executable sequence of slices. Each slice is independently shippable and has its own task document under [docs/tasks/](tasks/) covering:

- Goal + deliverables
- Files to reuse from CareerExplorer (verbatim copy / adapt / discard)
- New files to author from scratch
- Acceptance criteria + tests
- Dependencies on prior slices

The slices follow the roadmap in [ARCHITECTURE.md §12](ARCHITECTURE.md#12-roadmap), with one task doc per slice (`S01..S10`).

This document is the **index and the conventions reference**. The per-slice docs are the **actionable units of work**.

---

## 2. Reuse strategy

The CareerExplorer codebase already implements the *gentle visit* behaviors at production-grade quality. We extract them rather than rewrite them. For each slice, the per-slice task doc classifies every CareerExplorer file the slice touches into one of four buckets:

| Bucket | Meaning | Default action |
|---|---|---|
| **Copy** | Already generic; lift verbatim with only header/import edits and module-name changes. | `cp` then mechanical search/replace. |
| **Adapt** | Mostly generic but contains site-specific assumptions (URLs, schemas, identifiers). | Copy, then refactor named site-specific bindings into adapters / config. |
| **Reference** | Logic is useful as a template, but tangled with CareerExplorer's domain model (jobs, companies, search tasks). | Read for guidance; rewrite a clean implementation in `gsv.*`. |
| **Skip** | Site/business-specific. | Do not bring over. |

### 2.1 Top-level reuse map

| CareerExplorer source | Slices that touch it | Bucket |
|---|---|---|
| [`src/scraper/browser.py`](../../CareerExplorer/src/scraper/browser.py) | S1 (primitives, BrowserManager), S5 (HAR/trace/video lifecycle) | Copy + Adapt |
| [`src/scraper/auth.py`](../../CareerExplorer/src/scraper/auth.py) | S2 | Reference |
| [`src/scraper/jobs.py`](../../CareerExplorer/src/scraper/jobs.py) | S4 (interaction patterns), S10 (hydration retry, platform caps) | Reference |
| [`src/sessions.py`](../../CareerExplorer/src/sessions.py) | S5, S6 | Adapt |
| [`src/orchestrator_plan.py`](../../CareerExplorer/src/orchestrator_plan.py) | S8 | Copy |
| [`src/worker.py`](../../CareerExplorer/src/worker.py) (lines 244–326) | S7 (cancellation) | Adapt |
| [`src/worker.py`](../../CareerExplorer/src/worker.py) (lines ~71, 903–1089, 3050+) | S7 (lease, exit codes, heartbeat backoff) | Reference |
| [`src/config.py`](../../CareerExplorer/src/config.py) (`ScraperConfig`, `ObservabilityConfig`) | S1 + every later slice | Reference |
| [`docs/LINKEDIN.md`](../../CareerExplorer/docs/LINKEDIN.md) | All slices (rationale source) | Reference (read-only) |

Paths inside the `Copy` and `Adapt` buckets always become **`src/gsv/<package>/<module>.py`** in the new repo. The old `src.scraper.*` import paths are forbidden in the skeleton.

### 2.2 Generalization principles

When adapting CareerExplorer code, apply these transformations consistently:

1. **Strip domain identifiers.** No `linkedin`, `feed`, `job`, `company`, `search_task`, `vps` strings in the public API. Rename to neutral terms (`site`, `auth_marker`, `run`, `parameters`, `control_client`).
2. **Hoist hardcoded URLs into adapters.** Anything matching a URL or host string must come from the per-site config.
3. **Replace single concrete types with protocols.** `LinkedInSession` → `Session` + `SiteAuthAdapter`. `SearchTask` payloads → `Run` + opaque `parameters: dict`.
4. **Default to neutral locale/timezone.** CareerExplorer defaults to `es-ES` / `Europe/Madrid`. The skeleton defaults to `en-US` / `UTC`; sites override.
5. **Drop business-only counters.** `jobs_extracted`, `companies_seen` are app concerns. The framework only emits framework-level counters (`requests_made`, `cooldowns`, `hydration_retry_*`, `cancellation_boundary`, ...). Apps add their own via the open-ended `counters: dict[str, int]`.
6. **Preserve operational invariants.** Exit codes, heartbeat backoff tuple, lease TTL defaults, retention thresholds — these are load-bearing and stay numerically identical unless we have a reason to change them.

### 2.3 What we deliberately do NOT reuse

- CareerExplorer's database schemas (SQLite + ORM models)
- Search-task payload shapes (queries, filters, jobs, companies, attempts)
- The full worker control flow (3248 lines, deeply tangled with CE business logic) — extracted patterns only
- LinkedIn-specific selector lists, URL constants, pagination caps, panel-probe specifics
- The frontend / API stack
- Ansible roles tied to CareerExplorer service names

---

## 3. Slice index

Each row links to a per-slice task document. Slices ship in order; later slices may depend on earlier ones.

| Slice | Title | Depends on | Reuse summary | Task doc |
|---|---|---|---|---|
| S1 | Browser + primitives | — | Copy `scraper/browser.py` (split into 4 modules); minor adapter hooks | [S01-browser-and-primitives.md](tasks/S01-browser-and-primitives.md) |
| S2 | Session + auth | S1 | Reference `scraper/auth.py`; rewrite generically with `SiteAuthAdapter` | [S02-session-and-auth.md](tasks/S02-session-and-auth.md) |
| S3 | Pacing | S1 | Lift delay/dwell from `browser.py`; new `BurstGovernor`, `ContentAwareWait`, `DelayProfile` | [S03-pacing.md](tasks/S03-pacing.md) |
| S4 | Visit runner + steps | S1, S3 | New code; reference patterns from `scraper/jobs.py` | [S04-visit-runner.md](tasks/S04-visit-runner.md) |
| S5 | Observability | S1 | Copy session-dir/manifest/HAR lifecycle from `browser.py` + `sessions.py` retention | [S05-observability.md](tasks/S05-observability.md) |
| S6 | CLI | S5 | Adapt `sessions.py` Click commands; new `gsv run` and `gsv plan show` | [S06-cli.md](tasks/S06-cli.md) |
| S7 | Run + lease + cancel | S2, S4 | Adapt `worker.py` cancellation + lease patterns; new minimal dev server | [S07-run-lease-cancel.md](tasks/S07-run-lease-cancel.md) |
| S8 | Scheduling | S7 | Copy `orchestrator_plan.py` near-verbatim | [S08-scheduling.md](tasks/S08-scheduling.md) |
| S9 | Reference app | S1–S8 | New `apps/example/` against a public docs site | [S09-reference-app.md](tasks/S09-reference-app.md) |
| S10 | Hardening | S9 | Per-site rate caps; pagination/platform caps; integrity-audit-style probes | [S10-hardening.md](tasks/S10-hardening.md) |

A usable subset ships at the end of S6: visit a site under a CLI driver without lease/cancel/scheduling. S7 onward layers in coordinated, scheduled execution.

---

## 4. Conventions

These conventions apply to every slice. They are non-negotiable defaults; the per-slice docs only restate them when a slice has a specific exception.

### 4.1 Code

- **Python ≥ 3.10**, fully type-hinted (`from __future__ import annotations` at the top of each module).
- **No `src.*` imports.** All imports under the new package are `gsv.*`.
- **No app code under `src/gsv/`.** Apps live in `apps/<name>/` and depend on `gsv` only.
- **Public surface is the minimum needed.** Helpers stay underscore-prefixed unless cross-module reuse demands otherwise.
- **No global state.** Configuration is passed explicitly to constructors; rate-limiters, recorders, and pacing are owned by `BrowserManager` / `VisitContext`.
- **Async-first** (Playwright async API). Sync helpers are exceptions, not the norm.
- **Logging** uses `logging.getLogger(__name__)`. Format strings, no f-strings in log calls. Domain identifiers (run id, site, boundary) appear as structured keys.

### 4.2 Files and packages

- One responsibility per module; if a CareerExplorer source mixes concerns, the slice doc explicitly directs the split.
- New module = new test file under `tests/<package>/test_<module>.py`.
- Per-slice docs name every new file path; do not invent new files outside that list without updating the doc.

### 4.3 Tests

- **Determinism:** any test that consumes randomness uses a seeded `random.Random` injected via dependency. Default `Random()` is acceptable for production code only.
- **No real network.** Playwright tests run against a local fixture server (`tests/fixtures/server.py`) introduced in S1. Network tests against real sites belong in `apps/example/` smoke tests, not in `gsv` tests.
- **No real Chromium for unit tests.** Use Playwright's tracing/video off; for HAR/trace/video lifecycle tests, mock the Playwright `BrowserContext` boundary.
- **Coverage target:** ≥ 90% line on every new `gsv` module by S6. Slices state any module-specific exceptions.

### 4.4 Configuration

- All configurable values flow from YAML → `gsv.config.model.VisitorConfig` / `SiteConfig` (see S1).
- `${ENV_VAR}` interpolation supported.
- Per-site overrides shadow visitor-level defaults; the loader merges them at load time.
- No magic numbers in code. If a number is ever exposed to operators, it lives in the config dataclass.

### 4.5 Commits

- One slice = one branch (`feature/sNN-<short-name>`) → one PR.
- Per-slice docs may break a slice into multiple commits, but the PR is one logical unit.
- Commit messages reference the slice id (`S03: extract DelayProfile from CareerExplorer`).

### 4.6 Documentation

- Every new public module gets a one-paragraph module docstring.
- Architecture-level decisions go to [ARCHITECTURE.md](ARCHITECTURE.md). Implementation-level decisions go to the slice's task doc. Bug-level decisions go to commits.
- Update [ARCHITECTURE.md §14](ARCHITECTURE.md#14-open-questions) as open questions are resolved.

---

## 5. Slice summaries

Each subsection below is a one-paragraph orientation. The full task list lives in the linked task document.

### 5.1 S1 — Browser + primitives

Establish the bottom layer. Lift the `BrowserManager`, `RateLimiter`, and humanized interaction primitives (`random_delay`, `human_delay`, `random_mouse_move`, `click_with_position_jitter`, `human_type`, `scroll_page`, `run_humanized_page_dwell`) from `CareerExplorer/src/scraper/browser.py`. Split the single 557-line module into `gsv.browser.{manager,fingerprint,primitives,rate_limit}`. Replace `ScraperConfig` with new `gsv.config.VisitorConfig` and accept a per-site `allowed_host_globs` for HAR filter. → [S01-browser-and-primitives.md](tasks/S01-browser-and-primitives.md)

### 5.2 S2 — Session + auth

Generalize the LinkedIn login state machine from `CareerExplorer/src/scraper/auth.py`. Define `SiteAuthAdapter` (URLs, selector lists, predicates) and a `Session` class that runs the same five-stage flow (cookie → variant → credentials → submit → completion) against the adapter. Add `ChallengePolicy` (headed wait / headless fail). Add idempotent `post_login_warmup`. → [S02-session-and-auth.md](tasks/S02-session-and-auth.md)

### 5.3 S3 — Pacing

Promote the per-action gentle behaviors from S1 primitives into named, composable profiles. Introduce `DelayProfile` (production / recon / auth presets), `BurstGovernor` (every-N-actions cooldown), and `ContentAwareWait` (post-`goto` `wait_for_selector` + reaction delay + optional mouse move). These are the building blocks the visit runner injects around every step. → [S03-pacing.md](tasks/S03-pacing.md)

### 5.4 S4 — Visit runner + steps

Build `gsv.visit.*`: `VisitContext`, `VisitStep` protocol, `VisitPlan`, `VisitRunner`, and the built-in step library (`Navigate`, `Click`, `Type`, `Scroll`, `Dwell`, `WaitFor`, `Extract`, `Branch`, `ForEach`, `BurstCooldown`, `RecordEvent`). The runner enforces the canonical wrap (cancellation pre → rate-limit → execute → content-wait → delay → burst tick → cancellation post) around every step. → [S04-visit-runner.md](tasks/S04-visit-runner.md)

### 5.5 S5 — Observability

Lift the per-run session bundle (`manifest.json` + optional `trace.zip` / `network.har` / `video.webm` / `evidence.jsonl`) and retention CLI from `CareerExplorer/src/sessions.py`. Build `SessionRecorder` (open dir, write manifest, attach to BrowserManager), `SessionStore` (list/inspect/purge), and the three modes (`off`, `failures`, `always`) including success-path artifact cleanup. → [S05-observability.md](tasks/S05-observability.md)

### 5.6 S6 — CLI

Ship the `gsv` Click entrypoint: `gsv run <site> [--once] [--headed] [--observability=...]`, `gsv sessions {list,open,inspect,purge}`, and `gsv plan show` (read-only inspection of upcoming planned slots). The CLI is the demo surface for slices S1–S5 and the operator surface from S7+. → [S06-cli.md](tasks/S06-cli.md)

### 5.7 S7 — Run + lease + cancel

Introduce coordinated execution: `RunController` (claim → heartbeat → execute → submit → release), `LeaseClient` (HTTP wrapper over the six lease/run endpoints), `CancellationMonitor` and `RunCancellationRequested` (debounced poll, named boundaries, partial-result drain), exit code constants, and a SQLite-backed reference dev server (`gsv server dev`) that satisfies the API contract from [ARCHITECTURE.md §4.5](ARCHITECTURE.md#45-run--lease--cancel-layer-gsvrun). → [S07-run-lease-cancel.md](tasks/S07-run-lease-cancel.md)

### 5.8 S8 — Scheduling

Port `CareerExplorer/src/orchestrator_plan.py` near-verbatim into `gsv.schedule.plan`. The module is already pure (no I/O, RNG-injectable); only naming touches and import paths change. Wire it into the CLI (`gsv plan show`) and into the worker entrypoint that consumes `PlannedSlot`. → [S08-scheduling.md](tasks/S08-scheduling.md)

### 5.9 S9 — Reference app

Build `apps/example/` against a public, low-stakes target (TBD; default placeholder is a public docs site). Demonstrates the full stack: `auth.py` (a real `SiteAuthAdapter` for a no-auth public site is acceptable as a degenerate case), `selectors.py`, `visit.py` (a `VisitPlan` factory), `extractors.py`, `config.yaml`, and a `README.md` describing expected counters and artifacts. → [S09-reference-app.md](tasks/S09-reference-app.md)

### 5.10 S10 — Hardening

Add the foundational hardening needed for v0: per-site rate-limit overrides, framework-counter schema/versioning in manifests, and final documentation cleanup. Larger optional features from the original S10 scope are tracked as follow-up issues: pagination/platform caps, integrity probes, and per-step pacing controls. → [S10-hardening.md](tasks/S10-hardening.md)

---

## 6. Out of scope for v0

These are explicitly *not* delivered by S1–S10 and require their own future plan:

- Multi-site session pool inside one worker
- Proxy rotation / dual-IP testing
- Dedicated Postgres/FastAPI control-plane (the dev server in S7 is reference-only; production deployments supply their own)
- Distributed worker coordination beyond a single residential host
- A web UI for run/session inspection (CLI only in v0)
- CAPTCHA solving (manual escalation only)

## 6.1 Follow-up hardening candidates

The v0 baseline is complete after S10, but these opt-in features remain tracked for future releases:

- [#42](https://github.com/amendez13/gentle-site-visitor/issues/42) — pagination and platform caps for `ForEach`
- [#43](https://github.com/amendez13/gentle-site-visitor/issues/43) — integrity probes and per-step pacing controls
- [#41](https://github.com/amendez13/gentle-site-visitor/issues/41) — S9 app contract polish around app auth adapters, evidence docs, and trace/HAR interaction

---

## 7. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Selector drift in `apps/example/` reference site breaks S9 | Medium | Low | Reference app uses a stable public docs site; selectors live in `apps/example/selectors.py` and are easy to repair |
| `BrowserManager` HAR rotation quirk re-emerges with newer Playwright | Low | Medium | S5 task doc encodes the rotation pattern as a test that fails if context kwargs aren't honored |
| `worker.py` cancellation logic has unstated invariants | Medium | High | S7 references the original by line number; pull request includes a checklist mapping every CE invariant to a `gsv` test |
| Generic `SiteAuthAdapter` is not flexible enough for a real second site | Medium | Medium | S9 picks a site different enough from LinkedIn that the adapter is exercised; gaps go on the open-questions list, not into a refactor of S2 |
| Schedule planner's RNG seam diverges from CareerExplorer's tests | Low | Low | S8 ports the existing CareerExplorer test suite alongside the module |

---

## 8. Open questions

Tracked in [ARCHITECTURE.md §14](ARCHITECTURE.md#14-open-questions). When a slice resolves one, update both that doc and this row:

| Open question | Resolved in slice |
|---|---|
| 1. Dev server contract vs production | S7 |
| 2. Multi-session per worker | Out of scope (v0) |
| 3. Proxy support | Out of scope (v0) |
| 4. Schedule source of truth (YAML vs DB) | S8 (YAML for v0) |
| 5. Manifest schema evolution | S10 (`framework_counters_version: 1`) |
| 6. Test strategy for non-deterministic primitives | S1 resolved for browser primitives (seeded RNG seam); S8 keeps planner parity |
| 7. Per-app KV store | Out of scope (v0); revisit after S9 |

---

## 9. Where to start

A maintainer or agent picking this up should:

1. Read [ARCHITECTURE.md](ARCHITECTURE.md) end-to-end.
2. Read this document end-to-end.
3. Open [tasks/S01-browser-and-primitives.md](tasks/S01-browser-and-primitives.md) and follow it.
4. After S1 ships, choose either S2 or S3 (both are unblocked) — recommendation: S3 first because it tightens the primitives' contract before they get used by the visit runner in S4.

The task docs are the ground truth for *what* to do. This document is the orientation; [ARCHITECTURE.md](ARCHITECTURE.md) is the *why*.
