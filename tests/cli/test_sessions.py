"""Tests for `gsv sessions` commands."""

from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from gsv.cli import cli
from gsv.cli import sessions as sessions_module
from gsv.observability import BrowserMeta, RunRef, SessionManifest
from tests.cli.conftest import write_config


def write_session(
    base_dir: Path,
    session_id: str,
    *,
    run_id: str,
    outcome: str,
    mtime: int,
    artifacts: dict[str, str] | None = None,
) -> Path:
    """Create a synthetic session bundle."""
    session_dir = base_dir / session_id
    session_dir.mkdir(parents=True)
    manifest = SessionManifest(
        session_id=session_id,
        run=RunRef(id=run_id, plan_name="test", site="example"),
        started_at="2026-05-05T10:00:00Z",
        ended_at="2026-05-05T10:00:05Z",
        duration_seconds=5.0,
        outcome=outcome,  # type: ignore[arg-type]
        counters={"requests_made": 2},
        browser=BrowserMeta(headless=True),
        artifacts=artifacts or {"log": "worker.jsonl"},
    )
    (session_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    os.utime(session_dir / "manifest.json", (mtime, mtime))
    return session_dir


def test_sessions_list_table_and_json(tmp_path: Path, runner: CliRunner) -> None:
    """List renders newest-first table and parseable JSON."""
    write_session(tmp_path, "2026-05-05T100000Z_run-old", run_id="old", outcome="failed", mtime=10)
    write_session(tmp_path, "2026-05-05T110000Z_run-new", run_id="new", outcome="completed", mtime=20)

    table = runner.invoke(cli, ["sessions", "list", "--sessions-dir", str(tmp_path)])
    as_json = runner.invoke(cli, ["sessions", "list", "--sessions-dir", str(tmp_path), "--json"])

    assert table.exit_code == 0
    assert table.output.index("run-new") < table.output.index("run-old")
    assert "COUNTERS" in table.output
    assert as_json.exit_code == 0
    payload = json.loads(as_json.output)
    assert [item["run"] for item in payload] == ["new", "old"]


def test_sessions_list_without_site_reads_configured_site_subdirs(tmp_path: Path, runner: CliRunner) -> None:
    """All-site list aggregates one level below the configured sessions base."""
    config_path = write_config(tmp_path)
    write_session(
        tmp_path / "sessions" / "example",
        "2026-05-05T100000Z_run-one",
        run_id="one",
        outcome="completed",
        mtime=10,
    )

    result = runner.invoke(cli, ["--config", str(config_path), "sessions", "list", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["session_id"] == "2026-05-05T100000Z_run-one"


def test_sessions_inspect_counts_evidence_and_detects_ambiguous_prefix(tmp_path: Path, runner: CliRunner) -> None:
    """Inspect resolves exact prefixes and reports ambiguous prefixes clearly."""
    session_dir = write_session(
        tmp_path,
        "2026-05-05T100000Z_run-one",
        run_id="one",
        outcome="completed",
        mtime=10,
        artifacts={"evidence": "evidence.jsonl", "log": "worker.jsonl"},
    )
    (session_dir / "evidence.jsonl").write_text("{}\n{}\n", encoding="utf-8")
    write_session(tmp_path, "2026-05-05T100001Z_run-two", run_id="two", outcome="failed", mtime=11)

    exact = runner.invoke(cli, ["sessions", "inspect", "--sessions-dir", str(tmp_path), "2026-05-05T100000Z"])
    ambiguous = runner.invoke(cli, ["sessions", "inspect", "--sessions-dir", str(tmp_path), "2026-05-05T10"])

    assert exact.exit_code == 0
    assert "EVIDENCE_EVENTS: 2" in exact.output
    assert ambiguous.exit_code != 0
    assert "Ambiguous session prefix" in ambiguous.output


def test_sessions_inspect_json_includes_manifest(tmp_path: Path, runner: CliRunner) -> None:
    """Inspect JSON includes the raw manifest and evidence summary."""
    write_session(tmp_path, "2026-05-05T100000Z_run-one", run_id="one", outcome="completed", mtime=10)

    result = runner.invoke(cli, ["sessions", "inspect", "--sessions-dir", str(tmp_path), "--latest", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["manifest"]["run"]["id"] == "one"
    assert payload["evidence_events"] == 0


def test_sessions_open_prints_trace_command_when_npx_missing(tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
    """Open falls back to printing the trace path when npx is unavailable."""
    session_dir = write_session(
        tmp_path,
        "2026-05-05T100000Z_run-one",
        run_id="one",
        outcome="failed",
        mtime=10,
        artifacts={"trace": "trace.zip", "log": "worker.jsonl"},
    )
    (session_dir / "trace.zip").write_text("trace", encoding="utf-8")

    def missing_npx(*args, **kwargs):
        del args, kwargs
        raise FileNotFoundError("npx")

    monkeypatch.setattr(sessions_module.subprocess, "run", missing_npx)

    result = runner.invoke(cli, ["sessions", "open", "--sessions-dir", str(tmp_path), "--latest"])

    assert result.exit_code == 0
    assert "npx playwright show-trace" in result.output


def test_sessions_open_reports_viewer_failure(tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
    """Open reports a non-zero trace viewer result without crashing."""
    session_dir = write_session(
        tmp_path,
        "2026-05-05T100000Z_run-one",
        run_id="one",
        outcome="failed",
        mtime=10,
        artifacts={"trace": "trace.zip", "log": "worker.jsonl"},
    )
    (session_dir / "trace.zip").write_text("trace", encoding="utf-8")

    class Completed:
        returncode = 2

    def failed_viewer(*args, **kwargs):
        del args, kwargs
        return Completed()

    monkeypatch.setattr(sessions_module.subprocess, "run", failed_viewer)

    result = runner.invoke(cli, ["sessions", "open", "--sessions-dir", str(tmp_path), "--latest"])

    assert result.exit_code == 0
    assert "Trace viewer exited 2" in result.stderr


def test_sessions_purge_dry_run_reports_without_deleting(tmp_path: Path, runner: CliRunner) -> None:
    """Purge dry-run reports candidates and leaves directories in place."""
    write_session(tmp_path, "2026-05-05T100000Z_run-old", run_id="old", outcome="completed", mtime=10)
    write_session(tmp_path, "2026-05-05T110000Z_run-new", run_id="new", outcome="completed", mtime=20)

    result = runner.invoke(cli, ["sessions", "purge", "--sessions-dir", str(tmp_path), "--keep", "1", "--dry-run", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["candidates"][0]["session_id"] == "2026-05-05T100000Z_run-old"
    assert (tmp_path / "2026-05-05T100000Z_run-old").exists()


def test_sessions_purge_text_deletes_candidates(tmp_path: Path, runner: CliRunner) -> None:
    """Non-dry purge prints a text summary and deletes selected sessions."""
    write_session(tmp_path, "2026-05-05T100000Z_run-old", run_id="old", outcome="completed", mtime=10)
    write_session(tmp_path, "2026-05-05T110000Z_run-new", run_id="new", outcome="completed", mtime=20)

    result = runner.invoke(cli, ["sessions", "purge", "--sessions-dir", str(tmp_path), "--keep", "1"])

    assert result.exit_code == 0
    assert "Deleted: 1" in result.output
    assert not (tmp_path / "2026-05-05T100000Z_run-old").exists()
