"""Tests for session manifest serialization."""

from __future__ import annotations

from gsv.observability import BrowserMeta, RunRef, SessionManifest


def test_manifest_round_trip_preserves_open_counters() -> None:
    """Manifest JSON round-trip keeps open-ended counters and artifacts."""
    manifest = SessionManifest(
        session_id="2026-05-05T101500Z_run-run_1",
        run=RunRef(id="run_1", plan_name="smoke", parameters={"offset": 10}, site="example"),
        started_at="2026-05-05T10:15:00Z",
        ended_at="2026-05-05T10:16:00Z",
        duration_seconds=60.0,
        outcome="completed",
        counters={"requests_made": 3, "app_items": 2},
        browser=BrowserMeta(chromium_version="123", user_agent="ua", headless=True, viewport={"width": 1}),
        artifacts={"log": "worker.jsonl"},
    )

    assert SessionManifest.from_json(manifest.to_json()) == manifest


def test_manifest_includes_framework_counter_schema_version() -> None:
    """New manifests carry the framework-counter schema version."""
    manifest = SessionManifest(
        session_id="2026-05-05T101500Z_run-run_1",
        run=RunRef(id="run_1", plan_name="smoke"),
        started_at="2026-05-05T10:15:00Z",
    )

    assert manifest.to_dict()["framework_counters_version"] == 1


def test_manifest_tolerates_missing_optional_fields() -> None:
    """Older or partial manifests can still be loaded."""
    manifest = SessionManifest.from_json(
        '{"session_id":"2026-05-05T101500Z_run-a","run":{"id":"a","plan_name":"p"},"started_at":"now"}'
    )

    assert manifest.outcome == "in_progress"
    assert manifest.ended_at is None
    assert manifest.counters == {}
    assert manifest.framework_counters_version == 1
