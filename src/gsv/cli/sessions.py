# mypy: disable-error-code=misc
"""Session-bundle listing, inspection, opening, and retention commands."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, cast

import click

from gsv.cli._common import echo_json, handle_config_error, resolve_sessions_dir
from gsv.config import ConfigError
from gsv.observability.store import SessionRecord, SessionStore


@click.group("sessions")
def sessions_group() -> None:
    """Inspect session bundles."""


@click.command("list")
@click.option("--site", default=None, help="Site name; defaults to all sessions under the configured base dir.")
@click.option("--sessions-dir", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option("--outcome", default=None, help="Filter by manifest outcome.")
@click.option("--limit", default=None, type=int, help="Maximum records to print.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
@click.pass_context
def list_command(
    ctx: click.Context,
    site: str | None,
    sessions_dir: Path | None,
    outcome: str | None,
    limit: int | None,
    as_json: bool,
) -> None:
    """List parsed session manifests sorted newest first."""
    try:
        active_site = site or ctx.obj.get("site")
        resolved_dir = resolve_sessions_dir(ctx, site=active_site, sessions_dir=sessions_dir)
        records = _list_records(resolved_dir, recursive=active_site is None and sessions_dir is None)
    except Exception as exc:
        handle_config_error(exc)
        return
    if outcome:
        records = [record for record in records if record.outcome == outcome]
    if limit is not None:
        records = records[: max(0, limit)]

    if as_json:
        echo_json([_record_to_dict(record) for record in records])
        return
    click.echo(_records_table(records))


@click.command("inspect")
@click.argument("session_ref", required=False)
@click.option("--latest", is_flag=True, help="Inspect the newest session.")
@click.option("--site", default=None, help="Site name.")
@click.option("--sessions-dir", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
@click.pass_context
def inspect_command(
    ctx: click.Context,
    session_ref: str | None,
    latest: bool,
    site: str | None,
    sessions_dir: Path | None,
    as_json: bool,
) -> None:
    """Inspect one session manifest by id or unique prefix."""
    try:
        store = SessionStore(resolve_sessions_dir(ctx, site=site or ctx.obj.get("site"), sessions_dir=sessions_dir))
        record = _resolve_record(store, session_ref=session_ref, latest=latest)
    except Exception as exc:
        _handle_session_error(exc)
        return

    evidence_count = _evidence_count(record)
    if as_json:
        payload = _record_to_dict(record)
        payload["manifest"] = record.manifest
        payload["evidence_events"] = evidence_count
        echo_json(payload)
        return

    click.echo(f"SESSION_ID: {record.session_id}")
    click.echo(f"PATH: {record.path}")
    click.echo(f"RUN: {record.run_id}")
    click.echo(f"SITE: {record.site}")
    click.echo(f"OUTCOME: {record.outcome}")
    click.echo(f"DURATION: {_format_duration(record.duration_seconds)}")
    if record.counters:
        click.echo("COUNTERS:")
        for name, value in sorted(record.counters.items()):
            click.echo(f"  {name}: {value}")
    click.echo(f"ARTIFACTS: {', '.join(record.artifacts) if record.artifacts else '-'}")
    click.echo(f"EVIDENCE_EVENTS: {evidence_count}")
    click.echo("MANIFEST:")
    echo_json(record.manifest)


@click.command("open")
@click.argument("session_ref", required=False)
@click.option("--latest", is_flag=True, help="Open the newest session.")
@click.option("--site", default=None, help="Site name.")
@click.option("--sessions-dir", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.pass_context
def open_command(
    ctx: click.Context, session_ref: str | None, latest: bool, site: str | None, sessions_dir: Path | None
) -> None:
    """Open a session trace when available, otherwise print the session path."""
    try:
        store = SessionStore(resolve_sessions_dir(ctx, site=site or ctx.obj.get("site"), sessions_dir=sessions_dir))
        record = _resolve_record(store, session_ref=session_ref, latest=latest)
    except Exception as exc:
        _handle_session_error(exc)
        return

    trace_path = _artifact_path(record, "trace")
    if trace_path is None:
        click.echo(str(record.path))
        return

    try:
        completed = subprocess.run(["npx", "playwright", "show-trace", str(trace_path)], check=False)
    except FileNotFoundError:
        click.echo(f"Trace path: {trace_path}")
        click.echo(f"Install Playwright tooling or run: npx playwright show-trace {trace_path}")
        return
    if completed.returncode != 0:
        click.echo(f"Trace viewer exited {completed.returncode}. Trace path: {trace_path}", err=True)


@click.command("purge")
@click.option("--site", default=None, help="Site name.")
@click.option("--sessions-dir", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option("--older-than", default=None, type=int, help="Delete sessions older than N days.")
@click.option("--keep", default=None, type=int, help="Keep at most N newest sessions after age filtering.")
@click.option("--dry-run", is_flag=True, help="Plan deletions without removing directories.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
@click.pass_context
def purge_command(
    ctx: click.Context,
    site: str | None,
    sessions_dir: Path | None,
    older_than: int | None,
    keep: int | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Apply retention policy to session directories."""
    try:
        store = SessionStore(resolve_sessions_dir(ctx, site=site or ctx.obj.get("site"), sessions_dir=sessions_dir))
        result = store.purge(retention_days=older_than, max_sessions=keep, dry_run=dry_run)
    except Exception as exc:
        handle_config_error(exc)
        return

    payload = {
        "sessions_seen": result.sessions_seen,
        "kept_count": result.kept_count,
        "candidates": [
            {"session_id": candidate.session_id, "path": str(candidate.path), "reason": candidate.reason}
            for candidate in result.candidates
        ],
        "deleted_paths": [str(path) for path in result.deleted_paths],
        "failed_paths": [str(path) for path in result.failed_paths],
        "dry_run": dry_run,
    }
    if as_json:
        echo_json(payload)
        return
    action = "Would delete" if dry_run else "Deleted"
    click.echo(f"Sessions seen: {result.sessions_seen}")
    click.echo(f"Kept: {result.kept_count}")
    click.echo(f"{action}: {len(result.candidates) if dry_run else len(result.deleted_paths)}")
    for candidate in result.candidates:
        click.echo(f"  {candidate.session_id} {candidate.reason}")
    if result.failed_paths:
        click.echo("Failed paths:", err=True)
        for path in result.failed_paths:
            click.echo(f"  {path}", err=True)


def register(group: click.Group) -> None:
    """Register the sessions command group."""
    sessions_group.add_command(list_command)
    sessions_group.add_command(inspect_command)
    sessions_group.add_command(open_command)
    sessions_group.add_command(purge_command)
    group.add_command(sessions_group)


def _resolve_record(store: SessionStore, *, session_ref: str | None, latest: bool) -> SessionRecord:
    records = store.list()
    if latest:
        if not records:
            raise ValueError("No sessions found.")
        return records[0]
    if not session_ref:
        raise ValueError("Provide a session id prefix or --latest.")
    return store.inspect(session_ref)


def _list_records(sessions_dir: Path, *, recursive: bool = False) -> list[SessionRecord]:
    records = cast(list[SessionRecord], SessionStore(sessions_dir).list())
    if recursive and sessions_dir.exists():
        for child in sorted(sessions_dir.iterdir()):
            if child.is_dir():
                records.extend(cast(list[SessionRecord], SessionStore(child).list()))
        records.sort(key=lambda item: item.mtime_epoch, reverse=True)
    return records


def _record_to_dict(record: SessionRecord) -> dict[str, Any]:
    return {
        "session_id": record.session_id,
        "path": str(record.path),
        "run": record.run_id,
        "site": record.site,
        "outcome": record.outcome,
        "duration_seconds": record.duration_seconds,
        "counters": dict(record.counters),
        "parameters": record.parameters_summary,
        "artifacts": list(record.artifacts),
    }


def _records_table(records: list[SessionRecord]) -> str:
    headers = ("SESSION_ID", "RUN", "SITE", "OUTCOME", "DURATION", "COUNTERS", "ARTIFACTS")
    rows = [
        (
            record.session_id,
            record.run_id,
            record.site,
            record.outcome,
            _format_duration(record.duration_seconds),
            _format_counters(record.counters),
            ",".join(record.artifacts),
        )
        for record in records
    ]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], min(40, len(cell)))

    def line(values: tuple[str, ...]) -> str:
        return "  ".join(_truncate(value, widths[index]).ljust(widths[index]) for index, value in enumerate(values))

    output = [line(headers)]
    output.extend(line(row) for row in rows)
    return "\n".join(output)


def _format_duration(value: float | None) -> str:
    if value is None:
        return "-"
    if value < 60:
        return f"{value:.1f}s"
    minutes, seconds = divmod(int(value), 60)
    return f"{minutes}m{seconds:02d}s"


def _format_counters(counters: dict[str, int]) -> str:
    if not counters:
        return ""
    return " ".join(f"{name}={value}" for name, value in sorted(counters.items()))


def _truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[: max(0, width - 3)] + "..."


def _artifact_path(record: SessionRecord, name: str) -> Path | None:
    artifacts = record.manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    raw = artifacts.get(name)
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else record.path / path


def _evidence_count(record: SessionRecord) -> int:
    path = _artifact_path(record, "evidence")
    if path is None or not path.exists():
        return 0
    return sum(1 for _line in path.open("r", encoding="utf-8"))


def _handle_session_error(exc: Exception) -> None:
    if isinstance(exc, ConfigError):
        handle_config_error(exc)
    if isinstance(exc, (FileNotFoundError, ValueError)):
        raise click.ClickException(str(exc))
    handle_config_error(exc)
