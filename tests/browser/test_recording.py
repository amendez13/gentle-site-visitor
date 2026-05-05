"""Tests for browser recording lifecycle helpers."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest

from gsv.browser import BrowserManager
from gsv.config import ObservabilityConfig, SiteConfig, VisitorConfig
from gsv.observability import BrowserMeta, RunRef, SessionRecorder


class FakeTracing:
    """Tracing test double."""

    def __init__(self, *, fail_start: bool = False, fail_stop: bool = False) -> None:
        self.started = False
        self.stopped_path: str | None = None
        self.fail_start = fail_start
        self.fail_stop = fail_stop

    async def start(self, **kwargs: Any) -> None:
        if self.fail_start:
            raise RuntimeError("trace start failed")
        self.started = bool(kwargs)

    async def stop(self, *, path: str) -> None:
        if self.fail_stop:
            raise RuntimeError("trace stop failed")
        self.stopped_path = path
        Path(path).write_text("trace", encoding="utf-8")


class FakeContext:
    """Browser context test double."""

    def __init__(
        self,
        storage_state_payload: dict[str, Any] | None = None,
        *,
        fail_storage: bool = False,
        fail_trace_start: bool = False,
        fail_trace_stop: bool = False,
    ) -> None:
        self.storage_state_payload = storage_state_payload or {"cookies": [{"name": "s"}], "origins": []}
        self.closed = False
        self.fail_storage = fail_storage
        self.tracing = FakeTracing(fail_start=fail_trace_start, fail_stop=fail_trace_stop)
        self.default_timeout: int | None = None

    async def add_init_script(self, script: str) -> None:
        del script

    def set_default_timeout(self, timeout: int) -> None:
        self.default_timeout = timeout

    async def storage_state(self) -> dict[str, Any]:
        if self.fail_storage:
            raise RuntimeError("storage failed")
        return self.storage_state_payload

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    """Browser test double with sequential contexts."""

    version = "Chromium 123.0.0.0"

    def __init__(self) -> None:
        self.context_kwargs: list[dict[str, Any]] = []
        self.contexts: list[FakeContext] = []

    async def new_context(self, **kwargs: Any) -> FakeContext:
        self.context_kwargs.append(kwargs)
        context = FakeContext()
        self.contexts.append(context)
        return context


def build_manager(tmp_path: Path, observability: ObservabilityConfig) -> BrowserManager:
    """Create a recording-capable BrowserManager with fake internals."""
    manager = BrowserManager(
        VisitorConfig(observability=observability),
        SiteConfig(name="example", storage_path=str(tmp_path / "storage"), allowed_host_globs=["**/*.example.test/**"]),
        rng=random.Random(1),
    )
    browser = FakeBrowser()
    manager._browser = browser  # type: ignore[assignment]
    manager._context = FakeContext()  # type: ignore[assignment]
    return manager


def open_recorder(tmp_path: Path) -> SessionRecorder:
    """Open a recorder for browser tests."""
    recorder = SessionRecorder.open(
        sessions_dir=tmp_path / "sessions",
        mode="always",
        run=RunRef(id="r1", plan_name="plan"),
        browser_meta_provider=BrowserMeta,
    )
    assert recorder is not None
    return recorder


@pytest.mark.asyncio
async def test_trace_lifecycle_registers_artifact(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Tracing writes trace.zip through the attached recorder."""
    manager = build_manager(tmp_path, ObservabilityConfig(mode="always", trace=True))
    recorder = open_recorder(tmp_path)
    manager.attach_recorder(recorder)

    await manager.start_tracing()
    trace_path = await manager.stop_tracing()

    manifest = recorder.finalize(outcome="failed")
    assert trace_path == str(recorder.session_dir / "trace.zip")
    assert manifest.artifacts["trace"] == "trace.zip"


@pytest.mark.asyncio
async def test_enable_har_for_session_rotates_context_and_preserves_storage(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """HAR/video recording rotates context because options are context-creation-only."""
    manager = build_manager(tmp_path, ObservabilityConfig(mode="always", har=True, video=True))
    recorder = open_recorder(tmp_path)
    manager.attach_recorder(recorder)
    initial_context = manager.context

    await manager.enable_har_for_session()
    har_path = await manager.finalize_har()

    browser = manager._browser
    assert isinstance(browser, FakeBrowser)
    assert initial_context is not None
    assert initial_context.closed is True
    assert browser.context_kwargs[0]["storage_state"] == {"cookies": [{"name": "s"}], "origins": []}
    assert browser.context_kwargs[0]["record_har_path"] == str(recorder.session_dir / "network.har")
    assert browser.context_kwargs[0]["record_har_url_filter"] == "**/*.example.test/**"
    assert browser.context_kwargs[0]["record_video_dir"] == str(recorder.session_dir / "videos")
    assert browser.context_kwargs[0]["viewport"] == browser.context_kwargs[1]["viewport"]
    assert "record_har_path" not in browser.context_kwargs[1]
    assert har_path == str(recorder.session_dir / "network.har")
    assert recorder.finalize(outcome="failed").artifacts["har"] == "network.har"


@pytest.mark.asyncio
async def test_enable_har_noops_when_har_and_video_disabled(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """No recording context is created when both HAR and video are disabled."""
    manager = build_manager(tmp_path, ObservabilityConfig(mode="always", har=False, video=False))
    manager.attach_recorder(open_recorder(tmp_path))

    await manager.enable_har_for_session()

    browser = manager._browser
    assert isinstance(browser, FakeBrowser)
    assert browser.context_kwargs == []


def test_finalize_video_promotes_raw_files(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Raw Playwright video files are promoted into canonical artifact names."""
    manager = build_manager(tmp_path, ObservabilityConfig(mode="always", video=True))
    recorder = open_recorder(tmp_path)
    manager.attach_recorder(recorder)
    video_dir = recorder.session_dir / "videos"
    video_dir.mkdir()
    (video_dir / "raw.webm").write_text("video", encoding="utf-8")
    manager._recording._video_dir = video_dir

    video_path = manager.finalize_video()

    assert video_path == str(recorder.session_dir / "video.webm")
    assert (recorder.session_dir / "video.webm").exists()
    assert not video_dir.exists()
    assert recorder.finalize(outcome="failed").artifacts["video"] == "video.webm"


@pytest.mark.asyncio
async def test_recording_noops_without_enabled_mode_or_recorder(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Recording methods tolerate disabled modes and missing recorder/context state."""
    off_manager = build_manager(tmp_path, ObservabilityConfig(mode="off", trace=True, har=True))
    await off_manager.start_tracing()
    await off_manager.enable_har_for_session()
    assert await off_manager.stop_tracing() is None

    no_context = build_manager(tmp_path, ObservabilityConfig(mode="always", har=True))
    no_context._context = None  # type: ignore[assignment]
    no_context.attach_recorder(open_recorder(tmp_path))
    await no_context.start_tracing()
    await no_context.enable_har_for_session()
    assert no_context.finalize_video() is None


@pytest.mark.asyncio
async def test_trace_lifecycle_tolerates_start_and_stop_errors(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Trace failures are swallowed and clear tracing state."""
    start_fail = build_manager(tmp_path, ObservabilityConfig(mode="always", trace=True))
    start_fail._context = FakeContext(fail_trace_start=True)  # type: ignore[assignment]
    start_fail.attach_recorder(open_recorder(tmp_path))

    await start_fail.start_tracing()
    assert await start_fail.stop_tracing() is None

    stop_fail = build_manager(tmp_path, ObservabilityConfig(mode="always", trace=True))
    stop_fail._context = FakeContext(fail_trace_stop=True)  # type: ignore[assignment]
    stop_fail.attach_recorder(open_recorder(tmp_path))

    await stop_fail.start_tracing()
    assert await stop_fail.stop_tracing() is None


@pytest.mark.asyncio
async def test_har_rotation_tolerates_enable_and_finalize_errors(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Storage-state failures during HAR rotation are tolerated."""
    enable_fail = build_manager(tmp_path, ObservabilityConfig(mode="always", har=True))
    enable_fail._context = FakeContext(fail_storage=True)  # type: ignore[assignment]
    enable_fail.attach_recorder(open_recorder(tmp_path))

    await enable_fail.enable_har_for_session()
    assert enable_fail.har_path is None

    finalize_fail = build_manager(tmp_path, ObservabilityConfig(mode="always", har=True))
    finalize_fail.attach_recorder(open_recorder(tmp_path))
    await finalize_fail.enable_har_for_session()
    finalize_fail._context = FakeContext(fail_storage=True)  # type: ignore[assignment]

    assert await finalize_fail.finalize_har() is None


@pytest.mark.asyncio
async def test_finalize_har_returns_pending_path_without_active_context(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A pending HAR path is still reported if the context has already gone away."""
    manager = build_manager(tmp_path, ObservabilityConfig(mode="always", har=True))
    recorder = open_recorder(tmp_path)
    manager.attach_recorder(recorder)
    await manager.enable_har_for_session()
    manager._context = None  # type: ignore[assignment]

    assert await manager.finalize_har() == str(recorder.session_dir / "network.har")


def test_finalize_video_handles_empty_missing_and_multiple_video_dirs(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Video finalization handles empty, missing, and multi-file directories."""
    missing = build_manager(tmp_path, ObservabilityConfig(mode="always", video=True))
    recorder = open_recorder(tmp_path)
    missing.attach_recorder(recorder)
    missing._recording._video_dir = recorder.session_dir / "missing"
    assert missing.finalize_video() is None

    empty = build_manager(tmp_path, ObservabilityConfig(mode="always", video=True))
    empty.attach_recorder(recorder)
    empty_dir = recorder.session_dir / "empty"
    empty_dir.mkdir()
    empty._recording._video_dir = empty_dir
    assert empty.finalize_video() is None
    assert not empty_dir.exists()

    multiple = build_manager(tmp_path, ObservabilityConfig(mode="always", video=True))
    multiple.attach_recorder(recorder)
    multiple_dir = recorder.session_dir / "multiple"
    multiple_dir.mkdir()
    (multiple_dir / "b.webm").write_text("b", encoding="utf-8")
    (multiple_dir / "a.webm").write_text("a", encoding="utf-8")
    multiple._recording._video_dir = multiple_dir

    assert multiple.finalize_video() == str(recorder.session_dir / "video_0.webm")
    assert (recorder.session_dir / "video_0.webm").exists()
    assert (recorder.session_dir / "video_1.webm").exists()


def test_cleanup_artifacts_on_success_delegates_to_recorder_mode(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Browser cleanup delegates to the attached recorder/session mode."""
    manager = build_manager(tmp_path, ObservabilityConfig(mode="failures"))
    recorder = SessionRecorder.open(
        sessions_dir=tmp_path / "sessions",
        mode="failures",
        run=RunRef(id="cleanup", plan_name="plan"),
        browser_meta_provider=BrowserMeta,
    )
    assert recorder is not None
    manager.attach_recorder(recorder)
    (recorder.session_dir / "trace.zip").write_text("trace", encoding="utf-8")

    manager.cleanup_artifacts_on_success()

    assert not (recorder.session_dir / "trace.zip").exists()
