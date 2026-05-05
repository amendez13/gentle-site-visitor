# S7 — Run + lease + cancel

> **Slice:** S7 of 10. See [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md).
> **Architecture refs:** [ARCHITECTURE.md §4.5](../ARCHITECTURE.md#45-run--lease--cancel-layer-gsvrun), [§5.4 run/lease data model](../ARCHITECTURE.md#54-run--lease).
> **Status:** Implemented in PR for issue #17. **Depends on S2, S4.**

---

## 1. Goal

Introduce coordinated execution: a long-running `gsv worker` process that registers a lease, claims runs, executes them via `VisitRunner`, polls for cancellation at named boundaries, drains partial results on cancel, and submits outcomes. Ship a minimal SQLite-backed reference dev server (`gsv server dev`) that satisfies the API contract — production deployments are expected to plug in their own.

After this slice, an integration test should be able to:

1. Start `gsv server dev --port 8085` (in-process or subprocess).
2. Start `gsv worker --site example` against that server.
3. Insert a run via the dev server's admin API.
4. Observe the worker claim it, execute the visit, and submit `outcome=completed`.
5. Insert a second run, then cancel it mid-flight; observe the worker stop at the next boundary, submit partial results via `cancellation_ack`, and continue with the next run.
6. Heartbeat resilience: kill the dev server briefly while a run is executing; the worker retries `(5s, 15s, 30s)` and reregisters on `lease_expired`.

---

## 2. Deliverables

### 2.1 New modules

| Path | Source | Notes |
|---|---|---|
| `src/gsv/run/__init__.py` | new | Re-export public API. |
| `src/gsv/run/exit_codes.py` | from CE `worker.py` lines 80–83 (Copy) | `EXIT_OK`, `EXIT_RUNTIME_ERROR`, `EXIT_AUTH_FAILURE`, `EXIT_CONFIG_ERROR`. |
| `src/gsv/run/cancellation.py` | from CE `worker.py` lines 244–326 (Adapt) | `RunCancellationRequested`, `CancellationMonitor`. |
| `src/gsv/run/lease_client.py` | from CE `worker.py` lines 903–1089 + lines 71–77 (Adapt) | `LeaseClient` HTTP wrapper; backoff constants; lease state machine helpers. |
| `src/gsv/run/controller.py` | new (referencing CE `worker.py` main loop) | `RunController` orchestrating lease/claim/execute/submit/release. |
| `src/gsv/run/control_client.py` | new | Tiny HTTP client used by `CancellationMonitor` to poll `/api/runs/<id>/control`. Decoupled from `LeaseClient` for testing. |
| `src/gsv/server/__init__.py` | new | — |
| `src/gsv/server/dev/__init__.py` | new | — |
| `src/gsv/server/dev/app.py` | new | FastAPI app with the six endpoints from [ARCHITECTURE.md §4.5](../ARCHITECTURE.md#45-run--lease--cancel-layer-gsvrun) plus a small admin surface (`POST /admin/runs` to insert a run). |
| `src/gsv/server/dev/store.py` | new | SQLite schema + DAO: `runs`, `leases`, `submissions`, `cancellations`. |
| `src/gsv/cli/worker.py` | new | `gsv worker` long-running command. |
| `src/gsv/cli/server.py` | new | `gsv server dev` command. |

### 2.2 Modules to update

| Path | Change |
|---|---|
| `src/gsv/visit/context.py` (S4) | The `Cancellation` placeholder protocol gains a concrete implementation in `gsv.run.cancellation.CancellationMonitor`. The runner in S4 already calls `ctx.cancellation.check(...)`; no S4 code change. |
| `src/gsv/pacing/burst.py` (S3) | `BurstGovernor`'s `on_pre_cooldown` hook is now wired in `RunController.build_pacing()` to `cancellation.check(boundary="before_burst_cooldown")`. |
| `src/gsv/cli/main.py` (S6) | Register `worker` and `server` subcommand groups. |

### 2.3 New tests

| Path | Purpose |
|---|---|
| `tests/run/test_cancellation.py` | Debounced poll honors `min_poll_interval_seconds`; `force=True` overrides; raises `RunCancellationRequested` with `partials`; `boundary` is logged. |
| `tests/run/test_lease_client.py` | Backoff sequence on transient errors; reregister on `lease_expired`; terminal on `invalid_lease_token`; heartbeat success path. |
| `tests/run/test_controller.py` | Full lifecycle against a mocked `LeaseClient` and `ControlClient`; cancellation drains partials; auth failure exits 10. |
| `tests/server/dev/test_app.py` | Endpoints conform to the contract: register → claim → heartbeat → submit → release; control endpoint returns cancel state once `POST /admin/runs/<id>/cancel` is called. |
| `tests/integration/test_worker_endtoend.py` | Subprocess `gsv server dev` + `gsv worker` against fixture site; insert a run; assert success outcome and cancellation drain. |

---

## 3. Reuse map

| CE source | CE lines | Bucket | Becomes | Generalization |
|---|---|---|---|---|
| `src/worker.py` | 71–77 (heartbeat backoff & lease constants) | **Copy** | `gsv/run/lease_client.py` top-level constants | None. `_HEARTBEAT_RETRY_BACKOFF_SECONDS = (5, 15, 30)`, `_HEARTBEAT_MAX_TRANSIENT_FAILURES = 3`, `_HEARTBEAT_TRANSIENT_REASONS`, `_HEARTBEAT_REREGISTER_REASONS`, `_LEASE_TERMINAL_REASONS`, `_CLAIM_SELF_HEAL_REASONS`. |
| `src/worker.py` | 80–83 (exit code constants) | **Copy** | `gsv/run/exit_codes.py` | None. Public constants: `EXIT_OK=0`, `EXIT_RUNTIME_ERROR=1`, `EXIT_AUTH_FAILURE=10`, `EXIT_CONFIG_ERROR=20`. |
| `src/worker.py` | 244–276 (`TaskCancellationRequested`) | **Adapt** | `gsv/run/cancellation.py` `RunCancellationRequested` | Drop CE-specific `jobs`/`companies`/`attempts` fields; replace with a single `partials: dict[str, list[dict]]`. App code names its own keys (`{"items": [...], "skipped": [...]}`). The `with_partials` helper stays. `task_id: int` → `run_id: str`. |
| `src/worker.py` | 279–326 (`TaskCancellationMonitor`) | **Adapt** | `gsv/run/cancellation.py` `CancellationMonitor` | Replace `vps: VPSClient` and `vps.get_task_control(task_id)` with `client: ControlClient` and `client.get_run_control(run_id)`. Default `min_poll_interval_seconds=2.0` preserved. Boundary logging preserved. |
| `src/worker.py` | 903–926 (`register_worker_lease`) | **Reference** | `gsv/run/lease_client.py` `LeaseClient.register()` | Reimplement against `httpx.AsyncClient`; the response-shape contract (`{ok, lease_token, worker_id}`) matches the architecture. |
| `src/worker.py` | 928–963 (`heartbeat_worker_lease`) | **Reference** | `gsv/run/lease_client.py` `LeaseClient.heartbeat()` | Returns `(ok, payload)`; payload includes `reason` for transient classification. |
| `src/worker.py` | 964–984 (`release_worker_lease`) | **Reference** | `gsv/run/lease_client.py` `LeaseClient.release()` | None. |
| `src/worker.py` | 985–1088 (`claim_next_task`, `claim_task`) | **Reference** | `gsv/run/lease_client.py` `LeaseClient.claim_next()` / `claim(run_id)` | `claim_next` returns `Run | None`. Run shape is `{id, plan_name, parameters, ...}` — see Q1 below. |
| `src/worker.py` | 3050+ (heartbeat loop with backoff sleep & reregister) | **Reference** | `gsv/run/controller.py` `RunController._heartbeat_loop` | The main pattern: continuous `asyncio.create_task` heartbeat with `(5, 15, 30)` backoff, reregister on transient reasons, terminate on terminal reasons. Reimplemented cleanly; CE has many feature flags (`_STARTUP_AUTH_*`, etc.) we don't carry. |
| `src/worker.py` | (entire main loop) | **Skip** | — | 3248-line monolith. We extract patterns, not code. |

---

## 4. Step-by-step

### Step 7.1 — Exit codes

`src/gsv/run/exit_codes.py`:

```python
EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_AUTH_FAILURE = 10
EXIT_CONFIG_ERROR = 20
```

### Step 7.2 — Cancellation

`src/gsv/run/cancellation.py`:

```python
class RunCancellationRequested(RuntimeError):
    def __init__(self, run_id: str, *, reason: str | None = None, partials: dict[str, list[dict]] | None = None): ...

    def with_partials(self, partials: dict[str, list[dict]]) -> RunCancellationRequested: ...

class CancellationMonitor:
    def __init__(self, *, client: ControlClient, run_id: str, min_poll_interval_seconds: float = 2.0): ...

    @property
    def cancel_reason(self) -> str | None: ...

    async def check(self, *, force: bool = False, boundary: str = "") -> None: ...
```

`check()` semantics from CE preserved verbatim: debounce when `not force` and within interval, raise if a prior cancel was already observed; on poll, log boundary, raise on cancel. Polling failures are logged at debug and swallowed (the next call retries).

### Step 7.3 — Control client

```python
class ControlClient:
    def __init__(self, base_url: str, api_key: str, *, http: httpx.AsyncClient): ...

    async def get_run_control(self, run_id: str) -> dict[str, Any] | None: ...
```

Returns `{"cancel_requested": bool, "cancel_reason": str | None}` or `None` on transport error.

### Step 7.4 — Lease client

```python
class LeaseClient:
    def __init__(self, base_url: str, api_key: str, *, worker_id: str | None = None, http: httpx.AsyncClient): ...

    async def register(self) -> tuple[bool, dict[str, Any]]: ...
    async def heartbeat(self) -> tuple[bool, dict[str, Any]]: ...
    async def release(self) -> tuple[bool, dict[str, Any]]: ...

    async def claim_next(self, *, site: str) -> Run | None: ...
    async def claim(self, run_id: str) -> Run | None: ...
    async def submit(self, run_id: str, *, outcome: str, results: dict, error: str | None = None) -> bool: ...
    async def acknowledge_cancellation(self, run_id: str, *, partials: dict[str, list[dict]]) -> bool: ...
```

`Run` is a dataclass:

```python
@dataclass
class Run:
    id: str
    plan_name: str
    site: str
    parameters: dict[str, Any]
```

Backoff and self-heal logic encoded as helper functions (`should_reregister(reason) -> bool`, `should_terminate(reason) -> bool`) so the controller stays readable.

### Step 7.5 — RunController

```python
class RunController:
    def __init__(
        self,
        *,
        site: str,
        config: VisitorConfig,
        site_config: SiteConfig,
        site_adapter: SiteAuthAdapter,
        plan_factory: PlanFactory,
        lease_client: LeaseClient,
        control_client: ControlClient,
        recorder_factory: RecorderFactory,
    ): ...

    async def run_forever(self, *, poll_interval_seconds: int) -> int:
        """Returns an exit code."""
        ...

    async def run_once(self) -> int: ...
```

Internal loop:

1. `register_or_die()`. On terminal failure, exit 1.
2. Spawn `asyncio.create_task(self._heartbeat_loop())`.
3. Loop:
   a. `claim = await lease_client.claim_next(site=self.site)`.
   b. If none: `await asyncio.sleep(poll_interval_seconds)`.
   c. If claim: `await self._execute(run)`.
4. On Ctrl-C: cancel heartbeat task, `release()`, return 0.

`_execute(run)`:

1. Open `SessionRecorder` (S5).
2. Build `BrowserManager`, `Session`, `Pacing` (with `BurstGovernor.on_pre_cooldown` wired to cancellation), `CancellationMonitor`.
3. `await session.start()` / `login()` / `warmup()`.
4. Build `VisitContext` with the live `cancellation` and `recorder`.
5. `plan = plan_factory(visit_ctx)`.
6. `result = await VisitRunner(visit_ctx).run(plan)`.
7. `submit(run.id, outcome=result.outcome, results=result.extracted, error=result.error)`.
8. `recorder.finalize(...)`.
9. Catches `RunCancellationRequested` → `acknowledge_cancellation(partials)`, then continues the outer loop.

Auth failure (`session.login()` returns `False`): submit `outcome=blocked`, log, exit 10 in `run_once` mode; in `run_forever`, mark site as auth-broken (Q3) and exit 10.

### Step 7.6 — Dev server

`src/gsv/server/dev/store.py`: SQLite schema:

```sql
CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    plan_name TEXT NOT NULL,
    site TEXT NOT NULL,
    parameters TEXT NOT NULL,           -- JSON
    state TEXT NOT NULL DEFAULT 'pending', -- pending|claimed|completed|failed|cancelled|blocked
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    cancel_reason TEXT,
    claimed_by TEXT,                    -- worker_id
    claimed_at INTEGER,
    submitted_at INTEGER,
    outcome TEXT,
    result_payload TEXT,                -- JSON
    error TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE leases (
    worker_id TEXT PRIMARY KEY,
    lease_token TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    last_heartbeat INTEGER NOT NULL
);

CREATE TABLE cancellation_acks (
    run_id TEXT PRIMARY KEY,
    partials TEXT NOT NULL,
    received_at INTEGER NOT NULL
);
```

`src/gsv/server/dev/app.py` exposes the six endpoints:

```
POST /api/worker/lease/register
POST /api/worker/lease/heartbeat
POST /api/worker/lease/release
POST /api/runs/{id}/claim
GET  /api/runs/{id}/control
POST /api/runs/{id}/submit
POST /api/runs/{id}/cancellation_ack
```

Plus admin:

```
POST /admin/runs                          # body: {plan_name, site, parameters}
POST /admin/runs/{id}/cancel              # body: {reason}
GET  /admin/runs                          # for tests / inspection
```

`gsv server dev` runs uvicorn against this app on a configurable port. SQLite file path is `data/dev-server.sqlite` by default.

### Step 7.7 — CLI

`src/gsv/cli/worker.py`:

```python
@click.command("worker")
@click.option("--site", required=True)
@click.option("--once", is_flag=True)
@click.option("--poll-interval", default=300, type=int)
@click.pass_context
def worker_command(ctx, site, once, poll_interval): ...
```

Builds a `RunController` and calls `run_once` or `run_forever`.

`src/gsv/cli/server.py`:

```python
@click.group("server")
def server_group(): ...

@server_group.command("dev")
@click.option("--port", default=8085, type=int)
@click.option("--db", default="data/dev-server.sqlite", type=click.Path(path_type=Path))
def dev_command(port, db): ...
```

### Step 7.8 — Documentation

- `src/gsv/run/README.md`: state machine diagrams (lease lifecycle, run lifecycle, cancellation flow). Reference the API contract from §4.5.
- `src/gsv/server/dev/README.md`: schema, endpoints, "production deployments swap this out".

---

## 5. Acceptance criteria

- [x] `pytest tests/run tests/server/dev tests/integration/test_worker_endtoend.py` is green; coverage on `gsv.run` ≥ 90%.
- [x] `RunCancellationRequested` carries `partials` and is raised from `CancellationMonitor.check()` after a server says cancel.
- [x] Heartbeat backoff exactly matches `(5, 15, 30)` seconds; reregister fires on `lease_expired`/`lease_not_found`.
- [x] Worker exits 10 on auth failure, 20 on missing config, 1 on runtime error, 0 on graceful shutdown.
- [x] Cancellation drain: when the server flips `cancel_requested=True` mid-run, the worker stops at the next boundary, submits partials via `cancellation_ack`, and the run row's state is `cancelled`.
- [x] Dev server remains dependency-light for the server path (`fastapi` + `uvicorn` + stdlib `sqlite3`); worker HTTP calls use `httpx`.
- [x] No CE-specific identifiers (`task`, `vps`, `search_query`, `jobs_scraped`) in `gsv/run/` or `gsv/server/`.

---

## 6. Out of scope (deferred)

- Production server (Postgres + auth, RBAC, multi-worker fan-out) — operators implement this.
- Cancellation reasons taxonomy — server returns a free-form `cancel_reason` string; the worker logs it but doesn't branch on it.
- Multi-site workers — `--site` is mandatory in S7. Multi-site requires a session pool which is out of scope v0.

---

## 7. Dependencies

- Upstream: **S2** (Session), **S4** (VisitRunner + Cancellation seam), **S5** (SessionRecorder), **S6** (CLI base).
- Downstream blockers: **S8** (scheduling consumes the lease/claim API to fire planned slots), **S9** (reference app uses the worker).

---

## 8. Open questions

| ID | Question | Recommendation | Resolve in |
|---|---|---|---|
| Q1 | `Run.parameters` shape: opaque dict, or typed per-app? | Opaque dict at framework boundary; apps validate inside `plan_factory`. | S7 |
| Q2 | Should `CancellationMonitor` accept a list of "always force-check" boundaries? | No. The visit runner already calls `check()` at every step boundary; the debounce keeps it cheap. | S7 |
| Q3 | When auth fails in `run_forever`, exit immediately (matches CE) or back off and retry? | Exit. The exit-code-10 contract pages the operator. Auto-retry on auth failure can blackhole. | S7 |
| Q4 | Should the dev server require an API key? | Yes — even in dev. Default `GSV_API_KEY=dev`. Tests inject the key. Avoids accidental exposure if a user binds to 0.0.0.0. | S7 |
| Q5 | Run id format on the dev server? | UUIDv4 strings. Easy to test, no collision risk. | S7 |

---

## 9. Reviewer checklist

- [ ] All HTTP responses match the architecture contract verbatim (`reason` field on failures; `cancel_requested`/`cancel_reason` on control).
- [ ] Backoff tuple is the exact CE value `(5, 15, 30)`.
- [ ] Exit codes are the exact CE values `0/1/10/20`.
- [ ] `CancellationMonitor.check` accepts `boundary: str` and logs it.
- [ ] `BurstGovernor.on_pre_cooldown` is wired to `cancellation.check(boundary="before_burst_cooldown")`.
- [ ] `RunController` releases the lease in a `finally` block on every exit path.
- [ ] Dev server SQLite schema is documented in the slice and matches the code.
