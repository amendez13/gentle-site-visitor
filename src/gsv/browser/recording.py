"""Browser recording lifecycle helpers for session observability."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from gsv.observability import SessionRecorder, cleanup_session_artifacts_on_success

if TYPE_CHECKING:
    from gsv.browser.manager import BrowserManager

LOG = logging.getLogger(__name__)


class BrowserRecording:
    """Compose HAR, trace, and video lifecycle methods into ``BrowserManager``."""

    def __init__(self, manager: "BrowserManager") -> None:
        self._manager = manager
        self._recorder: SessionRecorder | None = None
        self._tracing_active = False
        self._har_path: str | None = None
        self._video_dir: Path | None = None

    def attach_recorder(self, recorder: SessionRecorder | None) -> None:
        """Attach the active session recorder."""
        self._recorder = recorder

    async def start_tracing(self) -> None:
        """Begin Playwright tracing when enabled and a session directory exists."""
        obs = self._manager.visitor.observability
        if obs.mode == "off" or not obs.trace:
            return
        if not self._manager.context or self._recorder is None:
            return
        try:
            await self._manager.context.tracing.start(screenshots=True, snapshots=True, sources=False)
            self._tracing_active = True
            LOG.info("Playwright tracing started for session %s", self._recorder.session_id)
        except Exception:
            LOG.warning("Failed to start Playwright tracing", exc_info=True)
            self._tracing_active = False

    async def stop_tracing(self) -> str | None:
        """Stop tracing and register ``trace.zip`` when available."""
        if not self._tracing_active or not self._manager.context or self._recorder is None:
            self._tracing_active = False
            return None
        trace_path = self._recorder.session_dir / "trace.zip"
        try:
            await self._manager.context.tracing.stop(path=str(trace_path))
            self._recorder.register_artifact("trace", trace_path)
            LOG.info("Playwright trace saved: %s", trace_path)
            return str(trace_path)
        except Exception:
            LOG.warning("Failed to stop Playwright tracing", exc_info=True)
            return None
        finally:
            self._tracing_active = False

    async def enable_har_for_session(self) -> None:
        """Rotate the context to enable HAR/video recording for the session."""
        obs = self._manager.visitor.observability
        if obs.mode == "off" or self._recorder is None:
            return
        if not self._manager.context or not self._manager._browser:
            return
        if not obs.har and not obs.video:
            return

        har_path = str(self._recorder.session_dir / "network.har") if obs.har else None
        video_dir = self._recorder.session_dir / "videos" if obs.video else None
        if video_dir is not None:
            video_dir.mkdir(parents=True, exist_ok=True)
        current_viewport = dict(self._manager._last_viewport) or None
        closed_old_context = False
        storage_state: object | None = None

        try:
            storage_state = await self._manager.context.storage_state()
            await self._manager.context.close()
            closed_old_context = True
            self._manager._context = await self._manager._browser.new_context(
                **self._manager._build_context_kwargs(
                    storage_state,
                    har_path=har_path,
                    video_dir=video_dir,
                    viewport=current_viewport,
                )
            )
            await self._manager._apply_context_defaults()
            self._har_path = har_path
            self._video_dir = video_dir
            LOG.info("Context recreated with session recording (har=%s video=%s)", bool(har_path), bool(video_dir))
        except Exception:
            LOG.warning("Failed to enable session recording", exc_info=True)
            if closed_old_context:
                await self._restore_baseline_context(storage_state, current_viewport)
            self._har_path = None
            self._video_dir = None

    async def finalize_har(self) -> str | None:
        """Flush HAR/video recording by rotating the context back to baseline."""
        if not self._har_path and not self._video_dir:
            return None

        har_path = self._har_path
        if not self._manager.context or not self._manager._browser:
            self._har_path = None
            return har_path

        closed_old_context = False
        storage_state: object | None = None
        current_viewport = dict(self._manager._last_viewport) or None
        try:
            storage_state = await self._manager.context.storage_state()
            await self._manager.context.close()
            closed_old_context = True
            self._manager._context = await self._manager._browser.new_context(
                **self._manager._build_context_kwargs(
                    storage_state,
                    viewport=current_viewport,
                )
            )
            await self._manager._apply_context_defaults()
            if har_path is not None and self._recorder is not None:
                self._recorder.register_artifact("har", har_path)
                LOG.info("HAR finalized: %s", har_path)
            if self._video_dir is not None and self._recorder is not None:
                LOG.info("Video recording finalized for session %s", self._recorder.session_id)
        except Exception:
            LOG.warning("Failed to finalize session recording", exc_info=True)
            if closed_old_context:
                await self._restore_baseline_context(storage_state, current_viewport)
            har_path = None
        finally:
            self._har_path = None
        return har_path

    async def _restore_baseline_context(self, storage_state: object, viewport: dict[str, int] | None) -> None:
        if not self._manager._browser:
            self._manager._context = None
            return
        try:
            self._manager._context = await self._manager._browser.new_context(
                **self._manager._build_context_kwargs(storage_state, viewport=viewport)
            )
            await self._manager._apply_context_defaults()
        except Exception:
            LOG.warning("Failed to restore browser context after recording failure", exc_info=True)
            self._manager._context = None

    def finalize_video(self) -> str | None:
        """Move recorded videos into canonical session filenames."""
        if self._recorder is None or self._video_dir is None:
            self._video_dir = None
            return None

        video_dir = self._video_dir
        self._video_dir = None
        if not video_dir.exists():
            return None

        videos = sorted(video_dir.glob("*.webm"))
        if not videos:
            self._cleanup_video_dir(video_dir)
            return None

        primary = self._promote_video_files(videos)
        self._cleanup_video_dir(video_dir)
        if primary is not None:
            self._recorder.register_artifact("video", primary)
        return primary

    @property
    def har_path(self) -> str | None:
        """Current HAR recording path, if active."""
        return self._har_path

    def cleanup_artifacts_on_success(self) -> None:
        """Remove heavy artifacts after success in failures-only mode."""
        if self._recorder is None:
            return
        cleanup_session_artifacts_on_success(self._recorder.session_dir, self._manager.visitor.observability.mode)

    def _promote_video_files(self, videos: list[Path]) -> str | None:
        if self._recorder is None:
            return None
        if len(videos) == 1:
            target = self._recorder.session_dir / "video.webm"
            videos[0].replace(target)
            return str(target)

        primary: str | None = None
        for index, source in enumerate(videos):
            target = self._recorder.session_dir / f"video_{index}.webm"
            source.replace(target)
            if primary is None:
                primary = str(target)
        LOG.warning("Multiple video artifacts detected for session %s", self._recorder.session_id)
        return primary

    @staticmethod
    def _cleanup_video_dir(video_dir: Path) -> None:
        try:
            video_dir.rmdir()
        except OSError:
            LOG.debug("Video temp directory not empty: %s", video_dir)
