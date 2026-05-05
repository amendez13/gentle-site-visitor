"""Retention policy for session bundles."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from gsv.observability.store import SessionRecord, list_session_records

DEFAULT_RETENTION_DAYS = 14
DEFAULT_MAX_SESSIONS = 100


@dataclass(frozen=True)
class RetentionCandidate:
    """Session directory selected for deletion."""

    session_id: str
    path: Path
    reason: str


@dataclass(frozen=True)
class RetentionResult:
    """Retention execution summary."""

    sessions_seen: int
    kept_count: int
    candidates: list[RetentionCandidate]
    deleted_paths: list[Path]
    failed_paths: list[Path]


def build_retention_plan(
    records: list[SessionRecord],
    *,
    retention_days: int | None,
    max_sessions: int | None,
    now_epoch: float | None = None,
) -> list[RetentionCandidate]:
    """Build the deletion plan for age and count limits."""
    if not records:
        return []

    now = now_epoch if now_epoch is not None else time.time()
    oldest_first = sorted(records, key=lambda item: item.mtime_epoch)
    chosen: dict[Path, RetentionCandidate] = {}

    if retention_days is not None and retention_days > 0:
        cutoff_epoch = now - (retention_days * 86400)
        for record in oldest_first:
            if record.mtime_epoch < cutoff_epoch:
                chosen[record.path] = RetentionCandidate(
                    session_id=record.session_id,
                    path=record.path,
                    reason=f"older_than_{retention_days}_days",
                )

    if max_sessions is not None and max_sessions >= 0:
        survivors = [record for record in oldest_first if record.path not in chosen]
        overflow_count = len(survivors) - max_sessions
        if overflow_count > 0:
            for record in survivors[:overflow_count]:
                chosen[record.path] = RetentionCandidate(
                    session_id=record.session_id,
                    path=record.path,
                    reason=f"exceeds_max_sessions_{max_sessions}",
                )

    return sorted(chosen.values(), key=lambda item: item.path.name)


def enforce_session_retention(
    sessions_dir: str | Path,
    *,
    retention_days: int | None,
    max_sessions: int | None,
    dry_run: bool = False,
    now_epoch: float | None = None,
) -> RetentionResult:
    """Apply retention policy to session directories."""
    records = list_session_records(sessions_dir)
    candidates = build_retention_plan(
        records,
        retention_days=retention_days,
        max_sessions=max_sessions,
        now_epoch=now_epoch,
    )
    deleted_paths: list[Path] = []
    failed_paths: list[Path] = []

    if not dry_run:
        for candidate in candidates:
            try:
                shutil.rmtree(candidate.path)
                deleted_paths.append(candidate.path)
            except OSError:
                failed_paths.append(candidate.path)

    kept_count = max(0, len(records) - len(candidates))
    return RetentionResult(
        sessions_seen=len(records),
        kept_count=kept_count,
        candidates=candidates,
        deleted_paths=deleted_paths,
        failed_paths=failed_paths,
    )
