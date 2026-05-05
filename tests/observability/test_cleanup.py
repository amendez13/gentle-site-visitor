"""Tests for success artifact cleanup."""

from __future__ import annotations

from gsv.observability import cleanup_session_artifacts_on_success


def test_failures_mode_success_cleanup_removes_heavy_artifacts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Failures mode strips only heavyweight artifacts after a completed run."""
    for name in ("trace.zip", "network.har", "video.webm", "video_1.webm", "manifest.json", "worker.jsonl"):
        (tmp_path / name).write_text("x", encoding="utf-8")

    cleanup_session_artifacts_on_success(tmp_path, "failures")

    assert sorted(path.name for path in tmp_path.iterdir()) == ["manifest.json", "worker.jsonl"]


def test_success_cleanup_noops_outside_failures_mode(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Always mode retains heavy artifacts."""
    (tmp_path / "trace.zip").write_text("x", encoding="utf-8")

    cleanup_session_artifacts_on_success(tmp_path, "always")

    assert (tmp_path / "trace.zip").exists()
