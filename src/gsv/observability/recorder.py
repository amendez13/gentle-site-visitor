"""Session recorder for per-run observability bundles."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gsv.observability.cleanup import cleanup_session_artifacts_on_success
from gsv.observability.manifest import BrowserMeta, ManifestOutcome, RunRef, SessionManifest

LOG = logging.getLogger(__name__)


class SessionRecorder:
    """Own a session directory, structured log, manifest, and registered artifacts."""

    def __init__(
        self,
        *,
        sessions_dir: Path,
        mode: str,
        run: RunRef,
        browser_meta_provider: Callable[[], BrowserMeta | dict[str, Any]],
        started_at: datetime | None = None,
    ) -> None:
        self.mode = mode
        self._run = run
        self._browser_meta_provider = browser_meta_provider
        self._started_at_dt = started_at or datetime.now(timezone.utc)
        stamp = self._started_at_dt.strftime("%Y-%m-%dT%H%M%SZ")
        self._session_id = f"{stamp}_run-{run.id}"
        self._session_dir = sessions_dir.expanduser() / self._session_id
        self._counters: dict[str, int] = {}
        self._artifacts: dict[str, str] = {}
        self._finalized = False

    @classmethod
    def open(
        cls,
        *,
        sessions_dir: str | Path,
        mode: str,
        run: RunRef,
        browser_meta_provider: Callable[[], BrowserMeta | dict[str, Any]],
        started_at: datetime | None = None,
    ) -> "SessionRecorder | None":
        """Open a session recorder, or return ``None`` when observability is off."""
        if mode == "off":
            return None
        recorder = cls(
            sessions_dir=Path(sessions_dir),
            mode=mode,
            run=run,
            browser_meta_provider=browser_meta_provider,
            started_at=started_at,
        )
        recorder._session_dir.mkdir(parents=True, exist_ok=True)
        recorder.register_artifact("log", "worker.jsonl")
        recorder._write_manifest(recorder._build_manifest(outcome="in_progress"))
        LOG.info("Session directory created: %s", recorder._session_dir)
        return recorder

    @property
    def session_dir(self) -> Path:
        """Return the session bundle directory."""
        return self._session_dir

    @property
    def session_id(self) -> str:
        """Return the session identifier."""
        return self._session_id

    def append_log(self, record: dict[str, Any]) -> None:
        """Append one JSON log record to ``worker.jsonl``."""
        self._session_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(record)
        payload.setdefault("session_id", self.session_id)
        with (self._session_dir / "worker.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")

    def update_counters(self, **delta: int) -> None:
        """Merge absolute counter values into the pending manifest counters."""
        for name, value in delta.items():
            self._counters[str(name)] = int(value)

    def register_artifact(self, name: str, path: str | Path) -> None:
        """Register an artifact path relative to the session directory when possible."""
        artifact_path = Path(path)
        try:
            value = str(artifact_path.relative_to(self._session_dir))
        except ValueError:
            value = str(artifact_path)
        self._artifacts[name] = value

    def finalize(
        self,
        *,
        outcome: str,
        error: str | None = None,
        ended_at: datetime | None = None,
    ) -> SessionManifest:
        """Finalize and atomically write ``manifest.json``."""
        ended_at_dt = ended_at or datetime.now(timezone.utc)
        normalized_outcome = _manifest_outcome(outcome)
        if normalized_outcome == "completed" and self.mode == "failures":
            cleanup_session_artifacts_on_success(self._session_dir, self.mode)
            self._artifacts = {
                name: path
                for name, path in self._artifacts.items()
                if name not in {"trace", "har", "video"} and not _is_success_cleanup_artifact(path)
            }
        manifest = self._build_manifest(
            outcome=normalized_outcome,
            error=error,
            ended_at=ended_at_dt,
        )
        self._write_manifest(manifest)
        self._finalized = True
        return manifest

    def _build_manifest(
        self,
        *,
        outcome: ManifestOutcome,
        error: str | None = None,
        ended_at: datetime | None = None,
    ) -> SessionManifest:
        browser_meta = self._browser_meta()
        duration = None
        ended_at_text = None
        if ended_at is not None:
            duration = max(0.0, ended_at.timestamp() - self._started_at_dt.timestamp())
            ended_at_text = _iso_utc(ended_at)
        return SessionManifest(
            session_id=self.session_id,
            run=self._run,
            started_at=_iso_utc(self._started_at_dt),
            ended_at=ended_at_text,
            duration_seconds=duration,
            outcome=outcome,
            error=error,
            counters=dict(self._counters),
            browser=browser_meta,
            artifacts=dict(self._artifacts),
        )

    def _browser_meta(self) -> BrowserMeta:
        raw = self._browser_meta_provider()
        if isinstance(raw, BrowserMeta):
            return raw
        return BrowserMeta.from_mapping(raw)

    def _write_manifest(self, manifest: SessionManifest) -> None:
        self._session_dir.mkdir(parents=True, exist_ok=True)
        target = self._session_dir / "manifest.json"
        temporary = self._session_dir / f".manifest.{time.monotonic_ns()}.tmp"
        temporary.write_text(manifest.to_json(), encoding="utf-8")
        temporary.replace(target)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _manifest_outcome(value: str) -> ManifestOutcome:
    if value in {"completed", "failed", "cancelled", "blocked", "in_progress"}:
        return value
    return "failed"


def _is_success_cleanup_artifact(path: str) -> bool:
    name = Path(path).name
    return name in {"trace.zip", "network.har", "video.webm"} or (name.startswith("video_") and name.endswith(".webm"))
