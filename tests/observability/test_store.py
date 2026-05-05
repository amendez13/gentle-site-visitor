"""Tests for session store helpers."""

from __future__ import annotations

import os
from pathlib import Path

from gsv.observability import RunRef, SessionManifest, SessionStore, list_session_records


def write_manifest(base: Path, session_id: str, *, run_id: str, outcome: str, mtime: float) -> None:
    """Create a synthetic session bundle."""
    session_dir = base / session_id
    session_dir.mkdir()
    manifest = SessionManifest(
        session_id=session_id,
        run=RunRef(id=run_id, plan_name="plan", parameters={"offset": 10}, site="example"),
        started_at="2026-05-05T10:00:00Z",
        ended_at="2026-05-05T10:01:00Z",
        duration_seconds=60,
        outcome="completed" if outcome == "completed" else "failed",
        counters={"requests_made": 3},
        artifacts={"log": "worker.jsonl", "trace": "trace.zip"},
    )
    manifest_path = session_dir / "manifest.json"
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")
    os.utime(manifest_path, (mtime, mtime))


def test_list_session_records_parses_manifests_and_ignores_noise(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Store listing parses valid session ids and sorts newest first."""
    write_manifest(tmp_path, "2026-05-05T100000Z_run-r1", run_id="r1", outcome="failed", mtime=100)
    write_manifest(tmp_path, "2026-05-05T100100Z_run-r2", run_id="r2", outcome="completed", mtime=200)
    (tmp_path / "not-a-session").mkdir()

    records = list_session_records(tmp_path)

    assert [record.run_id for record in records] == ["r2", "r1"]
    assert records[0].site == "example"
    assert records[0].counters == {"requests_made": 3}
    assert records[0].parameters_summary == "offset=10"
    assert records[0].artifacts == ["trace", "log"]


def test_session_store_inspect_resolves_unique_prefix(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """SessionStore.inspect resolves prefixes."""
    write_manifest(tmp_path, "2026-05-05T100000Z_run-r1", run_id="r1", outcome="failed", mtime=100)

    record = SessionStore(tmp_path).inspect("2026-05-05T100000Z")

    assert record.run_id == "r1"
