"""Session bundle listing and inspection helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SESSION_ID_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{6}Z_run-[A-Za-z0-9_-]+$")
_SESSION_RUN_SUFFIX_PATTERN = re.compile(r"_run-([A-Za-z0-9_-]+)$")
_MAX_PARAMETER_DISPLAY_LEN = 80


@dataclass(frozen=True)
class SessionRecord:
    """Parsed session record from ``<sessions_dir>/<session_id>/manifest.json``."""

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


class SessionStore:
    """Data-layer facade used by the later sessions CLI."""

    def __init__(self, sessions_dir: str | Path) -> None:
        self.sessions_dir = _resolve_sessions_dir(sessions_dir)

    def list(self) -> list[SessionRecord]:
        """Return parsed session records sorted newest first."""
        return list_session_records(self.sessions_dir)

    def inspect(self, session_ref: str) -> SessionRecord:
        """Return one record by exact id or unique prefix."""
        return resolve_session_record(self.list(), session_ref=session_ref)

    def purge(
        self,
        *,
        retention_days: int | None,
        max_sessions: int | None,
        dry_run: bool = False,
        now_epoch: float | None = None,
    ) -> Any:
        """Apply retention policy to the store."""
        from gsv.observability.retention import enforce_session_retention

        return enforce_session_retention(
            self.sessions_dir,
            retention_days=retention_days,
            max_sessions=max_sessions,
            dry_run=dry_run,
            now_epoch=now_epoch,
        )


def list_session_records(sessions_dir: str | Path) -> list[SessionRecord]:
    """Return parsed session records sorted by mtime descending."""
    base_dir = _resolve_sessions_dir(sessions_dir)
    if not base_dir.exists() or not base_dir.is_dir():
        return []

    records: list[SessionRecord] = []
    for entry in base_dir.iterdir():
        if not entry.is_dir() or not _SESSION_ID_PATTERN.match(entry.name):
            continue

        manifest_path = entry / "manifest.json"
        manifest = _load_manifest(manifest_path) if manifest_path.exists() else {}
        run = manifest.get("run") if isinstance(manifest.get("run"), dict) else {}
        run_id = _text(run.get("id")) if isinstance(run, dict) else ""
        if not run_id:
            run_id = _run_id_from_session_id(entry.name)
        site = _text(run.get("site")) if isinstance(run, dict) else ""
        outcome = _text(manifest.get("outcome")) or "unknown"
        duration_seconds = _safe_float(manifest.get("duration_seconds"))
        counters = _normalize_counters(manifest.get("counters"))
        parameters = run.get("parameters") if isinstance(run, dict) else {}
        artifacts = _normalize_artifacts(manifest.get("artifacts"))
        mtime_path = manifest_path if manifest_path.exists() else entry

        records.append(
            SessionRecord(
                session_id=entry.name,
                path=entry,
                manifest=manifest,
                run_id=run_id,
                site=site,
                outcome=outcome,
                duration_seconds=duration_seconds,
                counters=counters,
                parameters_summary=_summarize_parameters(parameters),
                artifacts=artifacts,
                mtime_epoch=mtime_path.stat().st_mtime,
            )
        )

    records.sort(key=lambda item: item.mtime_epoch, reverse=True)
    return records


def resolve_session_record(records: list[SessionRecord], *, session_ref: str) -> SessionRecord:
    """Resolve an exact session id or unique prefix from a record list."""
    exact = [record for record in records if record.session_id == session_ref]
    if exact:
        return exact[0]
    prefix_matches = [record for record in records if record.session_id.startswith(session_ref)]
    if not prefix_matches:
        raise ValueError(f"No session matching '{session_ref}'.")
    if len(prefix_matches) > 1:
        choices = ", ".join(record.session_id for record in prefix_matches[:5])
        raise ValueError(f"Ambiguous session prefix '{session_ref}'. Matches: {choices}")
    return prefix_matches[0]


def _resolve_sessions_dir(sessions_dir: str | Path) -> Path:
    return Path(sessions_dir).expanduser()


def _run_id_from_session_id(session_id: str) -> str:
    match = _SESSION_RUN_SUFFIX_PATTERN.search(session_id)
    return match.group(1) if match else ""


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _normalize_artifacts(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    preferred_order = ("trace", "har", "video", "log", "evidence")
    names: list[str] = []
    for key in preferred_order:
        if _text(value.get(key)):
            names.append(key)
    for key, artifact in value.items():
        name = str(key)
        if name in names:
            continue
        if _text(artifact):
            names.append(name)
    return names


def _normalize_counters(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counters: dict[str, int] = {}
    for key, item in value.items():
        try:
            counters[str(key)] = int(item)
        except (TypeError, ValueError):
            continue
    return counters


def _summarize_parameters(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    parts = [f"{key}={_truncate_text(str(item), max_len=24)}" for key, item in sorted(value.items())]
    return _truncate_text(" ".join(parts), max_len=_MAX_PARAMETER_DISPLAY_LEN)


def _truncate_text(value: str, *, max_len: int = _MAX_PARAMETER_DISPLAY_LEN) -> str:
    if len(value) <= max_len:
        return value
    return value[: max_len - 3] + "..."


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
