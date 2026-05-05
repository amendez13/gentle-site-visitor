# gentle-site-visitor

[CI workflow](../../actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10+-blue.svg)

A reusable skeleton for building applications that visit websites the way a real, attentive human does: authenticated, paced, and forensically observable.

Extracted and generalized from a production LinkedIn scraper. The premise is that a real Chromium binary on a residential connection, run at human cadence, is both effective and ethical. This is a **polite-visitor toolkit**, not a stealth/evasion toolkit.

## What it does

- **Authenticated sessions** — restore-or-login with cookie consent, variant detection, 2FA escalation, and idempotent post-auth warmup
- **Human-cadence interaction** — per-character typing delays, click-position jitter, mouse pathing, randomized dwell with scroll, distraction sleeps
- **Layered pacing** — per-action delay profiles (production/recon/auth), hourly `RateLimiter`, burst cooldowns after every N actions
- **Declarative visit plans** — compose `Navigate`, `Click`, `Type`, `Extract`, `Branch`, `ForEach`, and more; the framework wraps every step with pacing, rate-limiting, and cancellation
- **Scheduling** — daily activity windows, per-profile jitter, rest-period enforcement, RNG-injectable for deterministic tests
- **Cooperative cancellation** — cancel signals arrive at named boundaries; partial results are drained and submitted
- **Per-run observability** — `manifest.json`, optional Playwright trace + HAR + video, evidence JSONL, configurable retention
- **Lease-based coordination** — a server-coordinated run lifecycle (claim → heartbeat → execute → submit → release); ships a reference SQLite dev server

## Quick Start

```bash
git clone https://github.com/<repository-owner>/gentle-site-visitor.git
cd gentle-site-visitor
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
playwright install chromium
```

Run the reference app against the example site:

```bash
gsv config validate --site example
gsv run example --once --headed --observability=always
gsv sessions list --site example        # reads data/sessions/example by default
gsv sessions inspect --site example --latest
```

Plan the day's scheduled slots:

```bash
gsv plan show --site example --date 2026-05-04 --seed 42
```

Start the reference dev server and claim one queued run:

```bash
GSV_API_KEY=dev gsv server dev &
gsv worker --site example --once
```

Run from YAML schedule profiles:

```bash
GSV_API_KEY=dev gsv worker --site example --schedule
```

## Configuration

Configuration is YAML, with `${ENV_VAR}` interpolation and per-site overrides:

```yaml
visitor:
  headless: true
  manual_verification_timeout_seconds: 300
  pacing:
    profile: production        # production | recon | auth | disabled
    rate_limit_per_hour: 90
    burst_cooldown_interval: 5
    burst_cooldown_range: [30.0, 90.0]
    content_wait_timeout_ms: 10000
    content_wait_reaction_range: [0.5, 1.5]
    content_wait_with_mouse_move: true
    post_login_warmup: true
  observability:
    mode: failures             # off | failures | always
    retention_days: 14
    max_sessions: 100
  worker:
    api_url: http://127.0.0.1:8085
    api_key: ${GSV_API_KEY}
  schedule:
    activity_window_start: "08:00"
    activity_window_end: "23:00"
    rest_min_minutes: 30
    rest_max_minutes: 90
    profiles:
      - id: morning
        name: Morning visit
        frequency: weekdays
        preferred_time: "09:00"
        jitter_minutes: 30

sites:
  example:
    app_module: apps.example            # optional; defaults to apps.<site>
    rate_limit:                         # optional; omitted cap inherits visitor.pacing.rate_limit_per_hour
      requests_per_hour: 30
      window_minutes: 60
    auth:
      login_url: "https://example.com/login"
      auth_marker_url: "https://example.com/home"
      username_selectors: ["#username", "input[name='email']"]
      password_selectors: ["#password"]
      submit_selectors: ["button[type='submit']"]
    allowed_host_globs: ["*.example.com"]
    locale: en-US
    timezone_id: UTC
```

Validate with `gsv config validate --site example`.

## Architecture

Six layers, each independently testable:

```
Application layer     apps/<name>/  — adapter, selectors, plan factory, config
Visit layer           gsv.visit     — VisitPlan, VisitStep, VisitRunner, built-in steps
Pacing & realism      gsv.pacing    — DelayProfile, BurstGovernor, ContentAwareWait
Browser & session     gsv.browser   — BrowserManager, fingerprint, primitives
                      gsv.session   — SiteAuthAdapter, auth state machine, warmup
Run / lease / cancel  gsv.run       — RunController, LeaseClient, CancellationMonitor
Scheduling / obs.     gsv.schedule  — planner, PlannedSlot
                      gsv.observability — SessionRecorder, SessionStore, retention
```

Every visit step is wrapped by the framework:

```
cancellation_pre → rate_limit → execute → content_wait → delay → burst_tick → cancellation_post
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design, data model, sequence diagrams, and behavioral contract.

## Project Structure

```
gentle-site-visitor/
├── docs/
│   ├── ARCHITECTURE.md       # Full design document
│   ├── IMPLEMENTATION_PLAN.md
│   └── tasks/                # S01–S10 per-slice task documents
├── src/gsv/
│   ├── browser/              # BrowserManager, fingerprint, primitives, RateLimiter
│   ├── session/              # SiteAuthAdapter, auth state machine, warmup
│   ├── pacing/               # DelayProfile, BurstGovernor, ContentAwareWait
│   ├── visit/                # VisitContext, VisitPlan, VisitRunner, steps
│   ├── run/                  # RunController, LeaseClient, CancellationMonitor
│   ├── schedule/             # Planner, PlannedSlot, SchedulingRunner
│   ├── observability/        # SessionRecorder, SessionStore, retention
│   ├── config/               # VisitorConfig, SiteConfig, YAML loader
│   └── cli/                  # gsv entrypoint
├── apps/
│   └── example/              # Reference app (see docs/tasks/S09-reference-app.md)
├── tests/
├── AGENTS.md                 # Source-of-truth agent guidance
├── CLAUDE.md                 # Symlink to AGENTS.md
└── pyproject.toml
```

## Building an App

An app is a directory under `apps/<name>/` with five files:

| File | Purpose |
|---|---|
| `auth.py` | Concrete `SiteAuthAdapter` instance |
| `selectors.py` | All CSS selectors in one place |
| `visit.py` | `build_plan()` factory returning a `VisitPlan` |
| `extractors.py` | Pure async functions over `Page` |
| `config.yaml` | Site overrides on top of base config |

Apps never subclass framework classes; they compose via adapters and step lists. See [`apps/example/`](apps/example/) and the [app author checklist](docs/ARCHITECTURE.md#10-reference-application-contract).

## Development

```bash
# Install dev dependencies and hooks
pip install -r requirements-dev.txt
pre-commit install

# Run tests
pytest
pytest --cov=src/gsv --cov-report=term-missing

# Run all quality checks
pre-commit run --all-files

# Start the dev server
GSV_API_KEY=dev gsv server dev
```

Code quality: **Black** (formatting), **isort** (imports), **flake8** (linting), **mypy** (types), **bandit** (security), **pip-audit** (dependencies). All checks run via pre-commit hooks and CI.

## Worker exit codes

| Code | Meaning | Restart policy |
|---|---|---|
| `0` | Success | Normal |
| `1` | Runtime error | Auto-restart |
| `10` | Auth failure | No auto-restart — page operator |
| `20` | Config error | No auto-restart — page operator |

## Inspecting a failed run

```bash
gsv sessions list --outcome=failed
gsv sessions inspect <id-prefix>   # pretty manifest
gsv sessions open <id-prefix>      # Playwright Trace Viewer
gsv sessions purge --older-than 14 --dry-run
```

## CI/CD

GitHub Actions runs on every push and PR:

1. **Lint**: Black, isort, flake8, mypy
2. **Test**: pytest across Python 3.10, 3.11, 3.12
3. **Security**: bandit and pip-audit

See [docs/CI.md](docs/CI.md) for details.

## License

[Choose your license]
