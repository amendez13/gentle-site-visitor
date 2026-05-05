# gsv.observability

Per-run session bundles for auditability and failure diagnosis.

## Directory Layout

`SessionRecorder.open()` creates one directory under `visitor.observability.sessions_dir`:

```text
<sessions_dir>/<UTC-stamp>_run-<id>/
  manifest.json
  worker.jsonl
  evidence.jsonl
  trace.zip
  network.har
  video.webm
  video_*.webm
```

`manifest.json` is written when the recorder opens with `outcome="in_progress"` and rewritten atomically at finalize. `worker.jsonl` is owned by the recorder. `evidence.jsonl` is automatically selected as the `RecordEvent` sink when a `VisitContext` has a recorder and no custom sink.

## Manifest

`SessionManifest` has a stable top-level shape:

- `session_id`
- `run`: `RunRef(id, plan_name, parameters, site)`
- `started_at`, `ended_at`, `duration_seconds`
- `outcome`: `in_progress`, `completed`, `failed`, `cancelled`, or `blocked`
- `error`
- `counters`: open-ended framework and app counters
- `browser`: `BrowserMeta(chromium_version, user_agent, headless, viewport)`
- `artifacts`: artifact name to path relative to the session directory when possible

Counters are intentionally open-ended. Adding a counter does not require a manifest schema migration.

## Modes

- `off`: no recorder and no session directory.
- `failures`: record the bundle, then strip `trace.zip`, `network.har`, `video.webm`, and `video_*.webm` after `outcome="completed"`.
- `always`: record and retain all artifacts.

## Browser Recording

Playwright HAR and video settings are context-creation-only. `BrowserManager.enable_har_for_session()` preserves `storage_state`, closes the active context, and opens a new context with HAR/video options. `finalize_har()` rotates back to a baseline context and registers the HAR artifact. `finalize_video()` promotes Playwright's raw video files into `video.webm` or `video_<n>.webm`.

Attach the active recorder before starting trace/HAR/video lifecycle calls:

```python
recorder = SessionRecorder.open(
    sessions_dir=visitor.observability.sessions_dir,
    mode=visitor.observability.mode,
    run=RunRef(id=run_id, plan_name=plan_name, site=site.name),
    browser_meta_provider=browser.get_browser_metadata,
)
browser.attach_recorder(recorder)
```

The visit runner snapshots framework counters into the recorder, but the caller finalizes the recorder after browser recording teardown has registered artifacts:

```python
result = await VisitRunner(ctx).run(plan)
await browser.stop_tracing()
await browser.finalize_har()
browser.finalize_video()
recorder.finalize(outcome=result.outcome, error=result.error)
```

## Store And Retention

`SessionStore` and `list_session_records()` parse session directories for later CLI use. `enforce_session_retention()` applies the default retention model: delete sessions older than 14 days and then keep at most the newest 100 remaining sessions, oldest first.

Use `dry_run=True` to inspect the deletion plan without removing directories.
