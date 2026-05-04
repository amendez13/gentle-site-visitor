# AGENTS.md

This file provides guidance to coding agents working in this repository.
`CLAUDE.md` is a compatibility symlink to this file so Claude Code, Codex, and
other harnesses consume the same source of truth.

## Required Workflow Rules

1. Never skip pre-commit hooks.
   - Do not use `--no-verify`.
   - If hooks fail, fix the issues and rerun them.

2. Functional changes should go through a pull request by default.
   - Use a feature or fix branch unless the user explicitly requests a direct push to `main`.

3. Direct pushes to `main` are acceptable only when the user explicitly requests them.
   - Treat an explicit direct-push request as an override to the default PR workflow.
   - Still run the required validation before pushing.

4. Never change the code coverage target unless the user explicitly asks for that in the current task.

## Standard Delivery Workflow

For issue-driven work, follow this default sequence:

1. Checkout `main` and pull `origin/main`.
2. Create a branch for the issue (`feature/sNN-<short-name>`) and implement the change.
3. Update architecture, diagrams, and setup documentation when behavior, configuration, schema, API surface, or data flow changes.
4. Run the relevant tests.
5. Run `pre-commit run --all-files`.
6. Commit with a conventional commit message and push the branch.
7. Open a pull request with a closing keyword such as `Closes #X`.
8. Wait for CI to pass and fix failures before merge.
9. Request external review with `@codex review` or the repository's equivalent trigger.
10. While waiting, review your own diff and leave a PR comment covering the main change, primary risks, and any remaining validation gaps.
11. Read review feedback carefully, reply inline, fix the full class of problems, and create `[followup]` issues for deferred work when needed.
12. Leave a decision comment describing what was fixed now, deferred, declined, or not done.
13. Merge the pull request.
14. Return to the primary checkout, pull `origin/main`, update today's session note, then start the next issue.

## Session Notes

- Session notes are factual engineering notes stored under `notes/YYYY/MM/YYYY-MM-DD.md`.
- Agents must update session notes at the end of issue-driven delivery work, after merge, after deployment or manual follow-up, and when creating `[followup]` issues.
- Additive updates to session notes may be pushed directly to `main` when:
  - the change is only a session-note update, and
  - the user explicitly requested the notes update or the agent just completed a delivery cycle the user authorized.
- Use `ai-skills/session-notes/` as the canonical session-notes workflow.

---

## Project Overview

**Gentle Site Visitor** is a reusable Python skeleton for building applications that visit websites at human cadence: authenticated, paced, and forensically observable. It is extracted and generalized from a production LinkedIn scraper (CareerExplorer).

The skeleton is **not a stealth/evasion toolkit.** It is a *polite-visitor toolkit*: real Chromium, residential IP, human pacing. The goal is to be a low-impact visitor, not to evade detection while behaving badly.

**Core workflow:**

1. A daily planner produces a list of `PlannedSlot` with jitter and rest-period enforcement.
2. A worker wakes at each slot, acquires a lease from the coordination API, and starts a `RunController`.
3. `RunController` restores or establishes an authenticated `Session`, then runs a `VisitPlan`.
4. Every `VisitStep` is wrapped: `cancellation_pre → rate_limit → execute → content_wait → delay → burst_tick → cancellation_post`.
5. At run end the quality gate fires; the result (including partial on cancel) is submitted; the session bundle is finalized.

**Slice index (10 slices, ship in order):**

| Slice | Title | Issue |
|---|---|---|
| S1 | Browser + primitives | #11 |
| S2 | Session + auth | #12 |
| S3 | Pacing | #13 |
| S4 | Visit runner + steps | #14 |
| S5 | Observability | #15 |
| S6 | CLI | #16 |
| S7 | Run + lease + cancel | #17 |
| S8 | Scheduling | #18 |
| S9 | Reference app | #19 |
| S10 | Hardening | #20 |

---

## Architecture

### Technology Stack

- **Python 3.10+**, async-first (Playwright async API), fully type-hinted
- **Playwright** for Chromium browser automation
- **Click** for the `gsv` CLI
- **FastAPI + SQLite** for the reference dev server (`gsv server dev`)
- **dataclasses** for typed configuration and domain objects
- **pytest + pytest-asyncio** for tests

### Layer Model

```
apps/<name>/          — one directory per site (adapter, selectors, plan factory, config)
gsv.visit             — VisitPlan, VisitStep protocol, VisitRunner, built-in steps
gsv.pacing            — DelayProfile, BurstGovernor, ContentAwareWait
gsv.browser           — BrowserManager, fingerprint, human-cadence primitives, RateLimiter
gsv.session           — SiteAuthAdapter, auth state machine, ChallengePolicy, warmup
gsv.run               — RunController, LeaseClient, CancellationMonitor, exit codes
gsv.schedule          — planner (port of orchestrator_plan.py), PlannedSlot, SchedulingRunner
gsv.observability     — SessionRecorder, SessionManifest, SessionStore, retention
gsv.config            — VisitorConfig, SiteConfig, YAML loader with ${ENV} interpolation
gsv.cli               — gsv entrypoint (run, sessions, plan, config, server)
```

### Key Invariants — Do Not Break These

These values are operationally load-bearing (they match the original CareerExplorer production config and systemd restart policies):

- **Heartbeat backoff tuple: `(5, 15, 30)`** seconds. On transient lease failure, the worker retries at these intervals before giving up.
- **Exit codes:** `0` ok, `1` runtime error (auto-restart), `10` auth failure (no auto-restart), `20` config error (no auto-restart).
- **Lease TTL:** 120 seconds default. **Heartbeat interval:** 30 seconds default.
- **RateLimiter:** sliding-window per-hour cap. Default 90 requests/hour.
- **BurstGovernor:** every-N cooldown default: 5 actions → 30-90s sleep.
- **Retention:** 14 days OR 100 sessions max (whichever cuts more), oldest first.
- **Cancellation:** debounced poll, named boundaries (`*_pre`, `*_post`). Never violently kill a run.
- **No `src.*` imports anywhere.** All imports are `gsv.*`. Apps import from `gsv` only.
- **No app code inside `src/gsv/`.** Apps live in `apps/<name>/` only.

### Step Execution Wrap

Every `VisitStep` is wrapped by `VisitRunner` in this exact order:

```
1. cancellation.check(boundary=<step>_pre)
2. rate_limiter.acquire()
3. step.execute(ctx)
4. content_aware_wait.maybe_run(step.content_marker)
5. delay_profile.sleep()
6. burst_governor.tick()
7. cancellation.check(boundary=<step>_post)
```

This is the load-bearing abstraction. Do not move, skip, or reorder these stages.

### SiteAuthAdapter

Apps supply selectors and URLs; the framework runs the five-stage auth flow:

```
cookie_consent → variant_detection → credentials → submit → completion
```

Adapter fields: `login_url`, `auth_marker_url/predicate`, `cookie_consent_selectors`, `variant_trigger_selectors`, `username_selectors`, `password_selectors`, `submit_selectors`, `challenge_url_predicate`, `warmup_url`, `allowed_host_globs`.

Each selector field is a **list** — the framework tries each in order and accepts the first that resolves. This is intentional: sites change DOM.

### Observability

Per-run session bundle layout:

```
<sessions_dir>/<UTC-stamp>_run-<id>/
  manifest.json    — run metadata, outcome, counters, artifact paths
  worker.jsonl     — structured log lines
  trace.zip        — Playwright trace (opt-in)
  network.har      — HAR recording (opt-in)
  video.webm       — Playwright video (opt-in)
  evidence.jsonl   — app-defined structured events (RecordEvent steps)
  debug_artifacts/ — one-shot screenshots on failed extraction
```

**Important HAR/video quirk:** HAR and video must be set at context creation. To enable mid-run, `BrowserManager.enable_har_for_session()` saves `storage_state`, closes the context, and reopens it with recording enabled. Do not attempt to enable HAR on an existing context.

---

## Constraints and Best Practices

- This project is documentation-driven. Before starting a slice, read:
  - `docs/ARCHITECTURE.md` — full design and behavioral contract
  - `docs/IMPLEMENTATION_PLAN.md` — reuse strategy, conventions, slice index
  - `docs/tasks/SNN-<name>.md` — the specific slice task doc for the work being done
- After finishing a slice, update any documentation that changed with it.
- When changing schema, API surface, or data flow, update `docs/ARCHITECTURE.md` in the same PR.
- `pyproject.toml`, `.github/workflows/ci.yml`, and `.pre-commit-config.yaml` must stay aligned so local checks and CI behave the same way.
- Any code quality exception must be documented with an inline comment and a reason.
- Branch naming: `feature/sNN-<short-name>`, `fix/description`, `docs/description`
- Commit messages: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:` — prefix slice id when relevant: `S03: extract DelayProfile`

### What must NOT appear in `src/gsv/`

- `linkedin`, `feed`, `job`, `company`, `search_task`, `vps` — CareerExplorer business terms
- Hardcoded URLs or hostnames (must come from config or adapter)
- `import random` global usage — always inject `random.Random` for testability
- Site-specific selector strings
- `es-ES` or `Europe/Madrid` as defaults (skeleton defaults are `en-US` / `UTC`)

---

## Development Commands

### Initial Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
pre-commit install
playwright install chromium
```

### Running Tests

```bash
source venv/bin/activate
pytest
pytest --cov=src/gsv --cov-report=term-missing
pytest tests/browser/          # a specific package
pytest -k "test_rate_limiter"  # a specific test
```

### Code Quality

```bash
pre-commit run --all-files
black src/ tests/
isort src/ tests/
flake8 src/ tests/
mypy src/
bandit -r src/ -ll
```

### CLI Commands

```bash
gsv run <site> [--once] [--headed] [--observability=always|failures|off]
gsv sessions list [--site <name>] [--outcome failed|success|cancelled]
gsv sessions inspect [--site <name>] [--latest | <id-prefix>]
gsv sessions open [--site <name>] [--latest | <id-prefix>]
gsv sessions purge [--older-than <days>] [--keep <n>] [--dry-run]
gsv plan show [--site <name>] [--date YYYY-MM-DD] [--seed <n>] [--json]
gsv config validate [--site <name>]
gsv server dev [--port 8085]
gsv worker --site <name> [--schedule | --poll]
```

### Running the Dev Server

```bash
gsv server dev --port 8085
# Requires GSV_API_KEY env var; endpoints at http://127.0.0.1:8085/api/
```

---

## Notable Code Quality Exceptions

Document any non-default quality-rule exception in the file where it is used and keep the rationale brief and specific.

- `# noqa: C901` only when a step-dispatch or state-machine function is intentionally co-located and splitting it would reduce readability more than it helps.
- `# type: ignore[...]` only for incomplete third-party stubs (Playwright async types occasionally need this).
- `# nosec` only when the flagged pattern uses exclusively trusted internal input.

---

## Review Guidelines

- Treat CI, workflow, release, deployment, and setup-documentation regressions as P1 severity.
- When a change updates documentation or developer workflow files, verify the instructions still match the implementation.
- Treat broken bootstrap or operator guidance as a blocking issue when it would cause repository setup or delivery workflow failures.
- For each slice PR, verify the reviewer checklist in the slice's task doc (`docs/tasks/SNN-*.md`) before approving.
- Confirm no `linkedin`, `vps`, `job`, `company`, or `search_task` strings appear in `src/gsv/` or `tests/` (`grep -r linkedin src/ tests/` should return nothing).
