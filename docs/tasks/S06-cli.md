# S6 — CLI

> **Slice:** S6 of 10. See [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md).
> **Architecture refs:** [ARCHITECTURE.md §11 Operational playbook](../ARCHITECTURE.md#11-operational-playbook-skeleton).
> **Status:** Implemented. **Depends on S5.**

---

## 1. Goal

Ship the operator's surface for slices S1–S5 (and the foundation that S7+ extends): the `gsv` Click CLI.

After this slice, an operator should be able to:

```
gsv run <site> --once --headed --observability=always
gsv sessions list [--limit N] [--outcome ...] [--json]
gsv sessions open <id-prefix>
gsv sessions inspect <id-prefix>
gsv sessions purge [--older-than N] [--keep N] [--dry-run]
gsv plan show [--site <site>] [--date YYYY-MM-DD]    # placeholder; populated by S8
gsv config validate [<config.yaml>]
gsv --version
```

`gsv run` in S6 is a **single in-process driver** — it loads config, builds `BrowserManager` + `Session` + `VisitRunner`, and runs a single planned slot inline. It does NOT yet talk to a coordination server (no lease, no cancel poll). S7 layers that in.

---

## 2. Deliverables

### 2.1 New modules

| Path | Source | Notes |
|---|---|---|
| `src/gsv/cli/__init__.py` | new | Entry point: `cli()`. |
| `src/gsv/cli/_common.py` | new | Shared path resolution, redaction, and exit-code helpers for command modules. |
| `src/gsv/cli/main.py` | new | Top-level Click group; `--version`, `--config`, `--site` global options; subcommand registration. |
| `src/gsv/cli/run.py` | new | `gsv run` command. Loads config, opens recorder, builds runner, executes a `VisitPlan` factory imported from the configured app. |
| `src/gsv/cli/sessions.py` | from CE `src/sessions.py` lines 271–446 (Adapt) | `gsv sessions list/open/inspect/purge`. |
| `src/gsv/cli/plan.py` | new (placeholder; S8 fills) | `gsv plan show` — in S6 prints a "schedule integration coming in S8" notice; the command still parses and returns the upcoming-slots data structure once S8 lands. |
| `src/gsv/cli/config.py` | new | `gsv config validate <file>` — loads, applies env interpolation, prints resolved `VisitorConfig` + `SiteConfig` for a chosen site or all sites. |
| `src/gsv/apps/__init__.py` | new | Application registry: `register_app(name, plan_factory)` so `gsv run <site>` can resolve the plan. |
| `pyproject.toml` | update | `[project.scripts] gsv = "gsv.cli:cli"`. |

### 2.2 New tests

| Path | Purpose |
|---|---|
| `tests/cli/test_main.py` | `gsv --version` prints the version; `gsv --help` lists registered commands. |
| `tests/cli/test_apps.py` | Registry lookup/autoload behavior. |
| `tests/cli/test_run.py` | `gsv run <site> --once` with a stub app loads config, runs a synthetic `VisitPlan`, writes a session bundle. |
| `tests/cli/test_sessions.py` | List/inspect/purge against a synthetic sessions dir; `--json` output is well-formed; prefix resolution (`gsv sessions inspect 2026-`) handles ambiguity. |
| `tests/cli/test_config_validate.py` | Valid config returns 0; missing site key returns 20; missing `${ENV}` returns 20 with a clear message. |
| `tests/cli/test_plan.py` | Placeholder behavior in S6; S8 will replace with real assertions. |

---

## 3. Reuse map

| CE source | CE lines | Bucket | Becomes | Generalization |
|---|---|---|---|---|
| `src/sessions.py` | 271–299 (`_resolve_session_record`) | **Copy** | `gsv/cli/sessions.py` | Drop the `--task <id>` parameter; replace with `--run <id>` (run ids are strings, exact or prefix). The "session prefix matching" logic is preserved verbatim. |
| `src/sessions.py` | 302–308 (Click group `cli`) | **Copy** | `gsv/cli/sessions.py` | Mechanical: rename group to `sessions`, default `--sessions-dir` becomes `data/sessions/<site>` resolved from the active site config (Open question Q1). |
| `src/sessions.py` | 311–357 (`list_command`) | **Adapt** | `gsv/cli/sessions.py` | Header columns become `SESSION_ID, RUN, SITE, OUTCOME, DURATION, COUNTERS, ARTIFACTS`. `COUNTERS` column shows a compact summary (e.g., `requests=12 cooldowns=2`). The CE `JOBS` and `QUERY` columns are dropped. |
| `src/sessions.py` | 360–375 (`open_command`) | **Copy** | `gsv/cli/sessions.py` | None. Still launches `npx playwright show-trace`. Add a fallback that prints the path if `npx` is unavailable. |
| `src/sessions.py` | 378–401 (`inspect_command`) | **Copy** | `gsv/cli/sessions.py` | Mechanical: replace `record.manifest.get("error")` access with `SessionRecord.error` if S5 promoted that field; otherwise unchanged. Outcome color mapping kept. |
| `src/sessions.py` | 404–442 (`purge_command`) | **Copy** | `gsv/cli/sessions.py` | None. `_DEFAULT_RETENTION_DAYS=14` and `_DEFAULT_MAX_SESSIONS=100` constants live in `gsv/observability/retention.py` (S5). |

The `gsv run` command is **new code** — CE's worker entrypoint is not adaptable as-is because it runs a coordinated, lease-claimed loop. S6's `gsv run --once` is a degenerate single-shot of that loop without coordination.

---

## 4. Step-by-step

### Step 6.1 — CLI bootstrap

`src/gsv/cli/main.py`:

```python
@click.group(name="gsv")
@click.version_option(__version__)
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=Path("config/config.yaml"), show_default=True)
@click.pass_context
def cli(ctx: click.Context, config_path: Path) -> None:
    """Gentle Site Visitor."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
```

Subcommands are registered by `register_subcommands(cli)` invoked from `src/gsv/cli/__init__.py`. Each subcommand module exposes a `register(group)` function so the wiring stays compact.

### Step 6.2 — Application registry

`src/gsv/apps/__init__.py`:

```python
PlanFactory = Callable[["VisitContext"], "VisitPlan"]
_REGISTRY: dict[str, PlanFactory] = {}

def register_app(name: str, factory: PlanFactory) -> None: ...
def get_app(name: str) -> PlanFactory: ...

def autoload(site: SiteConfig) -> None:
    """Import `sites.<name>.app_module` or `apps.<name>` when available."""
```

Apps register themselves on import:

```python
# apps/example/__init__.py
from gsv.apps import register_app
from .visit import build_plan
register_app("example", build_plan)
```

`gsv run <site>` looks up the app by site name. `sites.<name>.app_module` is an optional import override for the uncommon case where a different module registers that site.

### Step 6.3 — `gsv run`

`src/gsv/cli/run.py`:

```python
@click.command("run")
@click.argument("site")
@click.option("--once", is_flag=True, help="Run a single visit immediately, ignoring schedule.")
@click.option("--headed/--headless", default=False)
@click.option("--observability", type=click.Choice(["off", "failures", "always"]), default=None)
@click.option("--profile", default=None, help="Override pacing profile.")
@click.pass_context
def run_command(ctx, site, once, headed, observability, profile): ...
```

Flow:

1. Load config from `ctx.obj["config_path"]`. Apply CLI overrides.
2. `apps.autoload(site_config)`.
3. Resolve `plan_factory = apps.get_app(site)`.
4. Resolve `Credentials.from_env(<SITE>_...)` if the site requires auth.
5. Build `BrowserManager(visitor, site)`; build `Session(browser, site_adapter, visitor)`.
6. If `observability != "off"`: open `SessionRecorder.open(...)` under `data/sessions/<site>/`, attach it to `BrowserManager`, set `ctx.recorder` for the runner.
7. `await session.start()`; if not authenticated, `await session.login(credentials)`. Handle `False` returns by raising a runtime error with exit code 10 (auth) — already in the architecture exit-code table.
8. `await session.post_login_warmup()`.
9. `plan = plan_factory(visit_ctx)`. Run via `VisitRunner(visit_ctx).run(plan)`.
10. Stop trace/HAR/video recording so browser artifacts are registered.
11. `recorder.finalize(outcome=visit_result.outcome, error=visit_result.error)`.
12. `await session.close()`.

Exit codes match the architecture: 0 ok, 1 runtime, 10 auth, 20 config.

### Step 6.4 — `gsv sessions`

Port CE Click commands from `src/sessions.py` lines 271–446. Generalizations:

- Default `--sessions-dir` resolves to `<visitor.observability.sessions_dir>/<site>` when a site is selected, or the base sessions directory for all-site listing. The `--sessions-dir` flag is a manual override.
- `list` columns: `SESSION_ID  RUN   SITE  OUTCOME  DURATION  COUNTERS  ARTIFACTS`.
- `open` falls back to printing the `trace.zip` path if `npx playwright show-trace` is missing (no `which npx` blocking).
- `inspect`: also pretty-prints `counters` as a sorted key-value list, since the CE manifest didn't have rich counters.
- `purge`: unchanged.

### Step 6.5 — `gsv plan show`

`src/gsv/cli/plan.py` placeholder for S6:

```python
@click.command("show")
@click.option("--date", default=None, help="YYYY-MM-DD (default: today).")
@click.pass_context
def show_command(ctx, date):
    click.echo("gsv plan show: schedule integration arrives in S8.", err=True)
    return
```

S8 replaces the body with real `compute_daily_plan` output rendering.

### Step 6.6 — `gsv config validate`

`src/gsv/cli/config.py`:

```python
@click.command("validate")
@click.argument("path", type=click.Path(path_type=Path), required=False)
@click.pass_context
def validate_command(ctx, path): ...
```

Loads YAML through the loader, prints resolved `visitor` and each site's resolved `SiteConfig` (with secrets redacted — any field name containing `password`, `secret`, `token`, or `api_key` printed as `***`).

### Step 6.7 — Logging configuration

The CLI initializes logging via `gsv.logging` (extend the template's existing `src/logging_config.py` to accept a verbosity flag). Default is `INFO`; `-v` switches to `DEBUG`.

### Step 6.8 — Documentation

- `src/gsv/cli/README.md`: command index, usage examples, exit codes table.
- Update [README.md](../../README.md) `## Quick start` to reference these commands once S6 ships.

---

## 5. Acceptance criteria

- [x] `pip install -e .` installs the `gsv` console script; `gsv --version` prints the package version.
- [x] `pytest tests/cli` is green; coverage ≥ 85% (CLI tests are integration-flavored).
- [x] `gsv run example --once --headed --observability=always` (with the stub app from `tests/cli/test_run.py`) runs end-to-end and writes a session bundle.
- [x] `gsv sessions list` against a directory of synthetic bundles prints a stable table; `--json` produces parseable output.
- [x] `gsv sessions purge --dry-run` reports candidates without deleting.
- [x] `gsv config validate config/config.yaml` returns exit 0 on valid; non-zero with a clear message otherwise.
- [x] Secrets are redacted in `gsv config validate` output.
- [x] `gsv` exits with code 10 on auth failure (login returns `False`); 20 on config errors.

---

## 6. Out of scope (deferred)

- `gsv plan show` real output — **S8**.
- `gsv worker` (long-running coordinated loop) — **S7**.
- `gsv server dev` (reference dev server) — **S7**.
- A web UI — out of scope v0.

---

## 7. Dependencies

- Upstream: **S1, S2, S3, S4, S5**.
- Downstream blockers: **S7** (registers `gsv worker` and `gsv server dev`), **S8** (fills `gsv plan show`).

---

## 8. Open questions

| ID | Question | Recommendation | Resolve in |
|---|---|---|---|
| Q1 | `data/sessions/` vs `data/sessions/<site>/`? | Resolved: `gsv run` writes per-site subdirectories and `gsv sessions --site` reads them by default. | S6 |
| Q2 | App lookup: by site name (`example`) or explicit app name in YAML (`apps.example`)? | Resolved: registry lookup is by site name; `sites.<name>.app_module` is an optional import override. | S6 |
| Q3 | Should `gsv run` accept `--credentials-from-env-prefix` as a CLI override, or only YAML? | Resolved: no CLI credential override; credential env prefix is derived from the site name. | S6 |
| Q4 | When `npx playwright show-trace` is missing on the operator's machine, fallback path? | Resolved: print the absolute `trace.zip` path and suggested manual command. | S6 |

---

## 9. Reviewer checklist

- [ ] No CE-specific column names (`QUERY`, `JOBS`) in `gsv sessions list`.
- [ ] `gsv run` exits with the documented codes; tests assert each non-zero path.
- [ ] Secrets are redacted in `config validate` output (test covers `password`, `api_key`, `token`, `secret`).
- [ ] Subcommand registration uses `register(group)` factories, not module-level decorators on the global group.
- [ ] `gsv plan show` placeholder prints to stderr and exits 0 (matching issue #16 acceptance criteria).
- [ ] `console_scripts` entry in `pyproject.toml` is updated; `pip install -e .` works.
