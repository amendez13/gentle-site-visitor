"""Tests for SessionRecorder."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from gsv.observability import BrowserMeta, RunRef, SessionManifest, SessionRecorder


def test_recorder_open_off_returns_none_without_directory(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Observability off does not allocate a session directory."""
    recorder = SessionRecorder.open(
        sessions_dir=tmp_path,
        mode="off",
        run=RunRef(id="r1", plan_name="plan"),
        browser_meta_provider=BrowserMeta,
    )

    assert recorder is None
    assert list(tmp_path.iterdir()) == []


def test_recorder_writes_logs_and_final_manifest(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Recorder opens a bundle, appends logs, and atomically writes final manifest."""
    recorder = SessionRecorder.open(
        sessions_dir=tmp_path,
        mode="failures",
        run=RunRef(id="r1", plan_name="plan", site="example"),
        browser_meta_provider=lambda: BrowserMeta(chromium_version="123"),
        started_at=datetime(2026, 5, 5, 10, 0, tzinfo=timezone.utc),
    )
    assert recorder is not None

    recorder.append_log({"event": "started"})
    recorder.update_counters(requests_made=2)
    recorder.register_artifact("trace", recorder.session_dir / "trace.zip")
    manifest = recorder.finalize(
        outcome="failed",
        error="boom",
        ended_at=datetime(2026, 5, 5, 10, 0, 5, tzinfo=timezone.utc),
    )

    loaded = SessionManifest.from_json((recorder.session_dir / "manifest.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (recorder.session_dir / "worker.jsonl").read_text(encoding="utf-8").splitlines()]
    assert loaded == manifest
    assert loaded.duration_seconds == 5.0
    assert loaded.framework_counters_version == 1
    assert loaded.counters == {"framework.requests_made": 2, "requests_made": 2}
    assert loaded.artifacts["trace"] == "trace.zip"
    assert rows == [{"event": "started", "session_id": recorder.session_id}]


def test_recorder_namespaces_framework_counters(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Framework counters are copied to stable framework-prefixed keys."""
    recorder = SessionRecorder.open(
        sessions_dir=tmp_path,
        mode="always",
        run=RunRef(id="r-counters", plan_name="plan"),
        browser_meta_provider=BrowserMeta,
    )
    assert recorder is not None

    recorder.update_counters(hydration_retries=1, app_items=2)

    manifest = recorder.finalize(outcome="completed")

    assert manifest.framework_counters_version == 1
    assert manifest.counters["hydration_retries"] == 1
    assert manifest.counters["framework.hydration_retries"] == 1
    assert manifest.counters["app_items"] == 2
    assert "framework.app_items" not in manifest.counters


def test_recorder_success_cleanup_keeps_manifest_and_log(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Failures mode removes heavy success artifacts during finalize."""
    recorder = SessionRecorder.open(
        sessions_dir=tmp_path,
        mode="failures",
        run=RunRef(id="r2", plan_name="plan"),
        browser_meta_provider=BrowserMeta,
    )
    assert recorder is not None
    for name in ("network.har", "trace.zip", "video.webm", "worker.jsonl"):
        (recorder.session_dir / name).write_text("x", encoding="utf-8")
    recorder.register_artifact("har", recorder.session_dir / "network.har")
    recorder.register_artifact("trace", recorder.session_dir / "trace.zip")
    recorder.register_artifact("video", recorder.session_dir / "video.webm")

    manifest = recorder.finalize(outcome="completed")

    assert (recorder.session_dir / "manifest.json").exists()
    assert (recorder.session_dir / "worker.jsonl").exists()
    assert not (recorder.session_dir / "network.har").exists()
    assert not (recorder.session_dir / "trace.zip").exists()
    assert not (recorder.session_dir / "video.webm").exists()
    assert manifest.artifacts == {"log": "worker.jsonl"}


def test_recorder_always_mode_retains_success_artifacts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Always mode keeps heavy artifacts and manifest entries on success."""
    recorder = SessionRecorder.open(
        sessions_dir=tmp_path,
        mode="always",
        run=RunRef(id="r3", plan_name="plan"),
        browser_meta_provider=BrowserMeta,
    )
    assert recorder is not None
    (recorder.session_dir / "trace.zip").write_text("trace", encoding="utf-8")
    recorder.register_artifact("trace", recorder.session_dir / "trace.zip")

    manifest = recorder.finalize(outcome="completed")

    assert (recorder.session_dir / "trace.zip").exists()
    assert manifest.artifacts["trace"] == "trace.zip"
