# S5 — Observability

> **Slice:** S5 of 10. See [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md).
> **Architecture refs:** [ARCHITECTURE.md §4.7](../ARCHITECTURE.md#47-observability-layer-gsvobservability), [§5.2 manifest schema](../ARCHITECTURE.md#52-session-manifest), [§5.3 evidence stream](../ARCHITECTURE.md#53-evidence-stream).
> **Status:** Implemented. **Depends on S1.**

---

## 1. Goal

Every run produces a self-contained, auditable session bundle. Lift the per-run session-directory contract, manifest schema, HAR/trace/video lifecycle, retention policy, and inspection helpers from CareerExplorer (`src/sessions.py` and the deferred parts of `src/scraper/browser.py`).

After this slice:

1. A `SessionRecorder` opens a session directory at run start and writes `manifest.json` at run end.
2. `BrowserManager` regains tracing/HAR/video lifecycle methods from CE (deferred from S1).
3. `JsonlEvidenceSink` (defined in S4) is wired automatically when the recorder is active.
4. `SessionStore.list/inspect/purge` work over a directory of session bundles.
5. Retention policy `(14 days OR 100 most recent)` enforces correctly.
6. Mode `failures` strips `trace.zip`/`video.webm` after a successful outcome (free retention for completed runs).

---

## 2. Deliverables

### 2.1 New modules

| Path | Source | Notes |
|---|---|---|
| `src/gsv/observability/__init__.py` | new | Re-export public API. |
| `src/gsv/observability/manifest.py` | new (referencing CE manifest fields seen in `sessions.py`) | `SessionManifest` dataclass, `BrowserMeta`, `RunRef` per [ARCHITECTURE.md §5.2](../ARCHITECTURE.md#52-session-manifest). JSON serialize/deserialize. |
| `src/gsv/observability/recorder.py` | new + lift from CE `browser.py` lines 257–274 (`init_session`) | `SessionRecorder` owns the session directory, opens the JSONL log, writes the manifest. |
| `src/gsv/observability/store.py` | from CE `src/sessions.py` lines 1–270 (Adapt) | `SessionRecord`, `list_session_records`, `_load_manifest`, `_normalize_artifacts`. |
| `src/gsv/observability/retention.py` | from CE `src/sessions.py` lines 170–242 (Copy) | `RetentionCandidate`, `RetentionResult`, `_build_retention_plan`, `enforce_session_retention`. |
| `src/gsv/observability/cleanup.py` | from CE `browser.py` lines 545–556 + `cleanup_artifacts_on_success` | `cleanup_session_artifacts_on_success(session_dir, mode)` for `mode=failures` post-success stripping. |
| `src/gsv/browser/recording.py` | from CE `browser.py` lines 339–500 (Adapt) | Tracing/HAR/video lifecycle methods extracted from `BrowserManager`. The `BrowserManager` (S1) gains `attach_recorder(recorder)` and the methods become composable. |

### 2.2 Modules to update

| Path | Change |
|---|---|
| `src/gsv/browser/manager.py` (S1) | Add `attach_recorder(recorder: SessionRecorder)`. Add `start_tracing`, `stop_tracing`, `enable_har_for_session`, `finalize_har`, `finalize_video`, `cleanup_artifacts_on_success` methods (delegating to `recording.py` helpers). |
| `src/gsv/visit/runner.py` (S4) | Accept an optional `recorder: SessionRecorder | None` on `VisitContext`. When set: emit framework counter snapshots into the manifest at run end; route `RecordEvent` to a `JsonlEvidenceSink` rooted at `recorder.session_dir / "evidence.jsonl"`. |
| `src/gsv/config/model.py` | Confirm `ObservabilityConfig`: `mode: Literal["off","failures","always"]`, `trace`, `har`, `video`, `sessions_dir`, `retention_days`, `max_sessions`, `har_content`. |

### 2.3 New tests

| Path | Purpose |
|---|---|
| `tests/observability/test_manifest.py` | Round-trip serialize/deserialize; counter dict is open-ended; missing optional fields tolerated. |
| `tests/observability/test_recorder.py` | Opens a directory under `tmp_path`; mode=`off` does not create a directory; mode=`failures` creates one and writes manifest at finalize; structured log lines appended to `worker.jsonl`. |
| `tests/observability/test_store.py` | `list_session_records` parses N synthetic session directories; `outcome` and `counters` propagate; non-matching directory names ignored. |
| `tests/observability/test_retention.py` | 14-day cutoff and `max_sessions=100` overlap correctly; `dry_run=True` removes nothing; failed unlinks reported in `failed_paths`. |
| `tests/observability/test_cleanup.py` | After success in mode=`failures`, `trace.zip` and `video.webm` removed; manifest and `worker.jsonl` retained. |
| `tests/browser/test_recording.py` | HAR/video kwargs added to context kwargs only when `obs.har` / `obs.video` are true; context rotation invariants (`enable_har_for_session` → `finalize_har` round-trip preserves storage_state). |

---

## 3. Reuse map

| CE source | CE lines | Bucket | Becomes | Generalization |
|---|---|---|---|---|
| `src/scraper/browser.py` | 247–274 (`session_dir`, `session_id`, `init_session`) | **Adapt** | `gsv/observability/recorder.py` `SessionRecorder.open(run_id, sessions_dir, mode)` | Replace `task_id: int` → `run_id: str` (run ids are server-assigned strings, not ints). Stamp format `<UTC>_run-<run_id>` matches the new `_SESSION_ID_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{6}Z_run-[A-Za-z0-9_-]+$"`. |
| `src/scraper/browser.py` | 339–372 (`start_tracing`, `stop_tracing`) | **Copy** | `gsv/browser/recording.py` | Mechanical: factor out of `BrowserManager` so `BrowserManager` only delegates. The implementation reads `obs.mode` and `obs.trace`, both already on the config. |
| `src/scraper/browser.py` | 374–449 (`enable_har_for_session`, `finalize_har`) | **Copy** | `gsv/browser/recording.py` | Critical invariant preserved: HAR/video options must be at context creation time, so we save `storage_state`, close, reopen with recording. |
| `src/scraper/browser.py` | 451–500 (`finalize_video`, `_promote_video_files`, `_cleanup_video_dir`) | **Copy** | `gsv/browser/recording.py` | None. |
| `src/scraper/browser.py` | 502–507 (`cleanup_artifacts_on_success` method) | **Copy** | `gsv/observability/cleanup.py` | Free function instead of method; takes `session_dir, mode`. |
| `src/scraper/browser.py` | 545–556 (free function `cleanup_session_artifacts_on_success`) | **Copy** | `gsv/observability/cleanup.py` | The pattern list `("trace.zip", "video.webm", "video_*.webm")` is generic and stays. |
| `src/sessions.py` | 1–110 (constants, dataclasses, helper functions, `_normalize_artifacts`) | **Adapt** | `gsv/observability/store.py` | Rename `task_id` → `run_id`. Drop `query` (LinkedIn-specific). Drop `jobs` (CE business count). The new `SessionRecord` exposes `counters: dict[str, int]` (extracted from `manifest.counters`) and a `parameters_summary` (top-level keys from `manifest.run.parameters`, truncated). |
| `src/sessions.py` | 113–167 (`list_session_records`) | **Adapt** | `gsv/observability/store.py` | Replace `_SESSION_ID_PATTERN` with the new run-id regex. Replace `task = manifest.get("task")` / `results = manifest.get("results")` access with `run = manifest.get("run")` / `counters = manifest.get("counters")`. Drop the `panel_probe` artifact key — apps register their own artifact keys; preferred order is `("trace", "har", "video", "log", "evidence")`. |
| `src/sessions.py` | 170–242 (`_build_retention_plan`, `enforce_session_retention`, `RetentionCandidate`, `RetentionResult`) | **Copy** | `gsv/observability/retention.py` | None — already site-agnostic. |
| `src/sessions.py` | 245–268 (display helpers `_truncate_query`, `_format_duration`, `_render_table`) | **Copy/Adapt** | `gsv/observability/store.py` (helpers) | `_truncate_query` becomes `_truncate_text(value, max_len)` — used to render arbitrary parameter strings, not specifically query strings. The Click commands themselves move to S6. |
| `src/sessions.py` | 271–end (Click subcommands `list`, `open`, `inspect`, `purge`) | **Defer to S6** | — | The CLI surface lives in `gsv/cli/sessions.py` (S6). S5 ships only the data-layer functions those commands call. |

---

## 4. Step-by-step

### Step 5.1 — Manifest

`gsv/observability/manifest.py`:

```python
@dataclass
class RunRef:
    id: str
    plan_name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    site: str = ""

@dataclass
class BrowserMeta:
    chromium_version: str = ""
    user_agent: str = ""
    headless: bool = True
    viewport: dict[str, int] = field(default_factory=dict)

@dataclass
class SessionManifest:
    session_id: str
    run: RunRef
    started_at: str          # ISO-8601 UTC
    ended_at: str | None = None
    duration_seconds: float | None = None
    outcome: Literal["completed", "failed", "cancelled", "blocked", "in_progress"] = "in_progress"
    error: str | None = None
    counters: dict[str, int] = field(default_factory=dict)
    browser: BrowserMeta = field(default_factory=BrowserMeta)
    artifacts: dict[str, str] = field(default_factory=dict)   # name -> relative path

    def to_json(self) -> str: ...

    @classmethod
    def from_json(cls, raw: str) -> SessionManifest: ...
```

The `counters` dict is intentionally open. `outcome="in_progress"` is the value during the run; `_finalize` rewrites it.

### Step 5.2 — SessionRecorder

`gsv/observability/recorder.py`:

```python
class SessionRecorder:
    def __init__(self, *, sessions_dir: Path, mode: Literal["off","failures","always"]): ...

    @classmethod
    def open(
        cls,
        *,
        sessions_dir: Path,
        mode: str,
        run: RunRef,
        browser_meta_provider: Callable[[], BrowserMeta],
    ) -> SessionRecorder | None:
        """Returns None when mode='off'."""
        ...

    @property
    def session_dir(self) -> Path: ...
    @property
    def session_id(self) -> str: ...

    def append_log(self, record: dict[str, Any]) -> None:
        """Append one JSON line to <session_dir>/worker.jsonl."""
        ...

    def update_counters(self, **delta: int) -> None: ...

    def register_artifact(self, name: str, path: str | Path) -> None: ...

    def finalize(self, *, outcome: str, error: str | None = None, ended_at: datetime | None = None) -> SessionManifest:
        """Write manifest.json and (if mode=failures + outcome=completed) cleanup heavy artifacts."""
        ...
```

The recorder owns the structured log file (`worker.jsonl`) and the manifest. It does NOT own the HAR/trace/video — those are owned by `BrowserManager` and registered into the recorder at finalize.

### Step 5.3 — Browser recording integration

`gsv/browser/recording.py`:

```python
class BrowserRecordingMixin:
    """Tracing/HAR/video methods composed into BrowserManager."""

    async def start_tracing(self) -> None: ...
    async def stop_tracing(self) -> str | None: ...
    async def enable_har_for_session(self) -> None: ...
    async def finalize_har(self) -> str | None: ...
    def finalize_video(self) -> str | None: ...
    @property
    def har_path(self) -> str | None: ...
```

Method bodies are copied from CE `browser.py` lines 339–500. The `BrowserManager` from S1 inherits or composes this mixin. **Decision**: composition over inheritance. `BrowserManager.__init__` constructs an internal `_recording = BrowserRecording(self)` and forwards method calls.

`BrowserManager.attach_recorder(recorder: SessionRecorder)` wires the recorder so `start_tracing`/`finalize_har`/`finalize_video` know where to write artifacts.

### Step 5.4 — Visit runner integration

`VisitContext` gains:

```python
recorder: SessionRecorder | None = None
```

When non-None, the runner:

- Calls `recorder.update_counters(**framework_counters)` at run end.
- Routes `RecordEvent` to `JsonlEvidenceSink(recorder.session_dir / "evidence.jsonl")` automatically. (S4 already accepts a sink; S5 just plugs the right one.)
- After plan completion, calls `recorder.finalize(outcome=visit_result.outcome, error=visit_result.error)`.

### Step 5.5 — Store

`gsv/observability/store.py`:

```python
@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    path: Path
    manifest: dict[str, Any]
    run_id: str
    site: str
    outcome: str
    duration_seconds: float | None
    counters: dict[str, int]
    parameters_summary: str
    artifacts: list[str]
    mtime_epoch: float

def list_session_records(sessions_dir: str | Path) -> list[SessionRecord]: ...
```

`parameters_summary` is a single-line render of `manifest.run.parameters` (e.g., `"site=example offset=0..50"`); apps may not put unbounded data in `parameters` but the renderer truncates anyway.

### Step 5.6 — Retention

Copy CE `_build_retention_plan` and `enforce_session_retention` near-verbatim into `gsv/observability/retention.py`. `RetentionCandidate.reason` strings are kept (`older_than_<n>_days`, `exceeds_max_sessions_<n>`).

### Step 5.7 — Cleanup

`gsv/observability/cleanup.py`:

```python
_SUCCESS_CLEANUP_PATTERNS = ("trace.zip", "video.webm", "video_*.webm", "network.har")

def cleanup_session_artifacts_on_success(session_dir: Path | None, mode: str) -> None:
    if mode != "failures" or session_dir is None:
        return
    for pattern in _SUCCESS_CLEANUP_PATTERNS:
        for artifact in session_dir.glob(pattern):
            artifact.unlink()
    if not any(session_dir.iterdir()):
        session_dir.rmdir()
```

**Difference from CE:** include `network.har` in the success-cleanup set. CE didn't strip it because the LinkedIn product wanted HAR retained on success. Our default mode says failures-only retention; HAR on a successful run is mostly noise.

### Step 5.8 — Documentation

- `src/gsv/observability/README.md`: directory layout, manifest fields, mode semantics, how to register custom artifacts.
- Update [ARCHITECTURE.md §14](../ARCHITECTURE.md#14-open-questions) Q5 (manifest evolution) — record the resolution: open-ended `counters: dict[str, int]` plus a stable top-level shape; no schema version field.

---

## 5. Acceptance criteria

- [x] `pytest tests/observability tests/browser/test_recording.py` is green; coverage ≥ 90%.
- [x] `SessionRecorder.open(mode="off", ...)` returns `None`; no directory is created.
- [x] `mode=failures` + outcome=`completed` strips `trace.zip`, `video.webm`, `video_*.webm`, and `network.har`; `manifest.json` and `worker.jsonl` remain.
- [x] `mode=failures` + outcome=`failed` retains all artifacts.
- [x] `mode=always` retains everything regardless of outcome.
- [x] `enforce_session_retention(retention_days=14, max_sessions=100)` matches CE behavior on a synthetic directory with mixed mtimes.
- [x] Manifest round-trip is stable (`SessionManifest.from_json(m.to_json())` equals `m`).
- [x] No `linkedin`, `feed`, `task_id`, `jobs_scraped`, or `panel_probe` strings in `src/gsv/observability/`.

---

## 6. Out of scope (deferred)

- CLI commands (`gsv sessions list/open/inspect/purge`) — **S6**.
- Streaming session events to a remote system — out of scope v0; apps can extend `SessionRecorder` if needed.
- A schema-version field on the manifest — see Q5 resolution above (intentionally not added).

---

## 7. Dependencies

- Upstream: **S1** (BrowserManager exists), **S4** (VisitContext + EvidenceSink protocol).
- Downstream blockers: **S6** (CLI), **S7** (worker writes initial manifest before browser starts).

---

## 8. Open questions

| ID | Question | Recommendation | Resolve in |
|---|---|---|---|
| Q1 | Should `network.har` be included in success-cleanup? | Yes — see §5.7. CE retained it for product reasons we don't share. | S5 |
| Q2 | Should the recorder be passed into `BrowserManager` at construction or via `attach_recorder`? | `attach_recorder` — the manager can be constructed before the recorder is opened (e.g., the worker may decide observability mode after lease claim). | S5 |
| Q3 | Run id is a string. What format? UUID? CE-style integer? | String, server-assigned. The skeleton accepts any matching `[A-Za-z0-9_-]+`. The dev server in S7 mints UUIDv4. | S5 |
| Q4 | Should retention enforcement run automatically at run end, or only via the CLI? | CLI + a documented systemd timer hook. Auto-enforcement at run end risks deleting artifacts the operator wants to inspect. | S5 |

---

## 9. Reviewer checklist

- [ ] No CE-specific manifest keys (`task`, `results.jobs_scraped`, `query`) in store.py.
- [ ] HAR/video lifecycle methods preserve storage_state across context rotation.
- [ ] Manifest `outcome` field accepts `"in_progress"` during execution (so a worker crash leaves an inspectable bundle).
- [ ] `SessionRecorder.open(mode="off")` is a true no-op (no `tmp` directory, no log file).
- [ ] `cleanup_session_artifacts_on_success` is a free function, callable from worker and from the CLI.
- [ ] Tests cover the three modes × two outcomes × HAR-on / HAR-off matrix where applicable.
