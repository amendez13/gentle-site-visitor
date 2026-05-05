"""Tests for session retention."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import gsv.observability.retention as retention_module
from gsv.observability import RunRef, SessionManifest, enforce_session_retention


def create_session(base: Path, session_id: str, *, mtime: float) -> None:
    """Create a synthetic session bundle with a manifest mtime."""
    session_dir = base / session_id
    session_dir.mkdir()
    manifest_path = session_dir / "manifest.json"
    manifest_path.write_text(
        SessionManifest(
            session_id=session_id,
            run=RunRef(id=session_id.rsplit("_run-", 1)[1], plan_name="plan"),
            started_at="2026-05-05T10:00:00Z",
        ).to_json(),
        encoding="utf-8",
    )
    os.utime(manifest_path, (mtime, mtime))


def test_retention_applies_age_and_max_session_limits(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Age and count policies overlap without double-counting candidates."""
    now = 1_000_000.0
    create_session(tmp_path, "2026-05-01T100000Z_run-old", mtime=now - 20 * 86400)
    create_session(tmp_path, "2026-05-02T100000Z_run-a", mtime=now - 100)
    create_session(tmp_path, "2026-05-03T100000Z_run-b", mtime=now - 50)
    create_session(tmp_path, "2026-05-04T100000Z_run-c", mtime=now)

    result = enforce_session_retention(tmp_path, retention_days=14, max_sessions=2, dry_run=True, now_epoch=now)

    assert result.sessions_seen == 4
    assert result.kept_count == 2
    assert [(item.session_id, item.reason) for item in result.candidates] == [
        ("2026-05-01T100000Z_run-old", "older_than_14_days"),
        ("2026-05-02T100000Z_run-a", "exceeds_max_sessions_2"),
    ]
    assert result.deleted_paths == []
    assert all(path.exists() for path in (tmp_path / item.session_id for item in result.candidates))


def test_retention_real_mode_deletes_candidates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Real retention removes selected session directories."""
    now = 1_000_000.0
    create_session(tmp_path, "2026-05-01T100000Z_run-old", mtime=now - 20 * 86400)

    result = enforce_session_retention(tmp_path, retention_days=14, max_sessions=100, dry_run=False, now_epoch=now)

    assert [path.name for path in result.deleted_paths] == ["2026-05-01T100000Z_run-old"]
    assert result.failed_paths == []
    assert not (tmp_path / "2026-05-01T100000Z_run-old").exists()


def test_retention_kept_count_reflects_failed_deletions(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Partial deletion failures are counted as kept sessions in real mode."""
    now = 1_000_000.0
    create_session(tmp_path, "2026-05-01T100000Z_run-a", mtime=now - 20 * 86400)
    create_session(tmp_path, "2026-05-02T100000Z_run-b", mtime=now - 20 * 86400)
    original_rmtree = shutil.rmtree

    def fake_rmtree(path: Path) -> None:
        if path.name.endswith("run-a"):
            raise OSError("locked")
        original_rmtree(path)

    monkeypatch.setattr(retention_module.shutil, "rmtree", fake_rmtree)

    result = enforce_session_retention(tmp_path, retention_days=14, max_sessions=100, now_epoch=now)

    assert [path.name for path in result.deleted_paths] == ["2026-05-02T100000Z_run-b"]
    assert [path.name for path in result.failed_paths] == ["2026-05-01T100000Z_run-a"]
    assert result.kept_count == 1
