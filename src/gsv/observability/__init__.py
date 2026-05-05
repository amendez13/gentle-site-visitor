"""Observability API for session bundles."""

from __future__ import annotations

from gsv.observability.cleanup import cleanup_session_artifacts_on_success
from gsv.observability.manifest import BrowserMeta, RunRef, SessionManifest
from gsv.observability.recorder import SessionRecorder
from gsv.observability.retention import (
    DEFAULT_MAX_SESSIONS,
    DEFAULT_RETENTION_DAYS,
    RetentionCandidate,
    RetentionResult,
    build_retention_plan,
    enforce_session_retention,
)
from gsv.observability.store import SessionRecord, SessionStore, list_session_records, resolve_session_record

__all__ = [
    "BrowserMeta",
    "DEFAULT_MAX_SESSIONS",
    "DEFAULT_RETENTION_DAYS",
    "RetentionCandidate",
    "RetentionResult",
    "RunRef",
    "SessionManifest",
    "SessionRecord",
    "SessionRecorder",
    "SessionStore",
    "build_retention_plan",
    "cleanup_session_artifacts_on_success",
    "enforce_session_retention",
    "list_session_records",
    "resolve_session_record",
]
