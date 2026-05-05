"""SQLite store for the reference dev coordination server."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any


class DevServerStore:
    """Small SQLite DAO for leases, runs, submissions, and cancellation acks."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def register_lease(self, *, worker_id: str, lease_ttl_seconds: int) -> dict[str, Any]:
        lease_token = uuid.uuid4().hex
        now = _now()
        ttl = max(1, int(lease_ttl_seconds))
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO leases(worker_id, lease_token, expires_at, last_heartbeat)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    lease_token=excluded.lease_token,
                    expires_at=excluded.expires_at,
                    last_heartbeat=excluded.last_heartbeat
                """,
                (worker_id, lease_token, now + ttl, now),
            )
        return {"ok": True, "worker_id": worker_id, "lease_token": lease_token}

    def heartbeat(self, *, worker_id: str, lease_token: str, lease_ttl_seconds: int = 120) -> dict[str, Any]:
        with self._connect() as con:
            lease = con.execute("SELECT * FROM leases WHERE worker_id = ?", (worker_id,)).fetchone()
            if lease is None:
                return {"ok": False, "reason": "lease_not_found"}
            if str(lease["lease_token"]) != lease_token:
                return {"ok": False, "reason": "invalid_lease_token"}
            now = _now()
            if int(lease["expires_at"]) < now:
                return {"ok": False, "reason": "lease_expired"}
            con.execute(
                "UPDATE leases SET expires_at = ?, last_heartbeat = ? WHERE worker_id = ?",
                (now + max(1, int(lease_ttl_seconds)), now, worker_id),
            )
        return {"ok": True}

    def release(self, *, worker_id: str, lease_token: str) -> dict[str, Any]:
        with self._connect() as con:
            con.execute("DELETE FROM leases WHERE worker_id = ? AND lease_token = ?", (worker_id, lease_token))
        return {"ok": True}

    def create_run(self, *, plan_name: str, site: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO runs(id, plan_name, site, parameters, state, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (run_id, plan_name, site, _json(parameters or {}), _now()),
            )
        return self.get_run(run_id) or {}

    def claim_next(self, *, site: str, worker_id: str, lease_token: str) -> dict[str, Any]:
        lease_check = self._validate_lease(worker_id, lease_token)
        if not lease_check["ok"]:
            return lease_check
        with self._connect() as con:
            claimed = con.execute(
                """
                UPDATE runs
                SET state = 'claimed', claimed_by = ?, claimed_at = ?
                WHERE id = (
                    SELECT id FROM runs
                    WHERE site = ? AND state = 'pending'
                    ORDER BY created_at, id
                    LIMIT 1
                )
                AND state = 'pending'
                RETURNING id
                """,
                (worker_id, _now(), site),
            ).fetchone()
            if claimed is None:
                return {"ok": True, "run": None}
            run_id = str(claimed["id"])
        return {"ok": True, "run": self.get_run(run_id)}

    def claim(self, *, run_id: str, worker_id: str, lease_token: str) -> dict[str, Any]:
        lease_check = self._validate_lease(worker_id, lease_token)
        if not lease_check["ok"]:
            return lease_check
        with self._connect() as con:
            run = con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                return {"ok": False, "reason": "run_not_found"}
            state = str(run["state"])
            if state == "claimed":
                if str(run["claimed_by"]) == worker_id:
                    return {"ok": True, "run": self.get_run(run_id)}
                return {"ok": False, "reason": "run_already_claimed"}
            if state != "pending":
                return {"ok": False, "reason": "run_not_claimable"}
            con.execute(
                "UPDATE runs SET state = 'claimed', claimed_by = ?, claimed_at = ? WHERE id = ?",
                (worker_id, _now(), run_id),
            )
        return {"ok": True, "run": self.get_run(run_id)}

    def control(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if not run:
            return {"cancel_requested": False, "cancel_reason": None}
        return {
            "cancel_requested": bool(run.get("cancel_requested")),
            "cancel_reason": run.get("cancel_reason"),
        }

    def submit(
        self,
        *,
        run_id: str,
        worker_id: str,
        lease_token: str,
        outcome: str,
        results: dict[str, Any],
        error: str | None,
    ) -> dict[str, Any]:
        lease_check = self._validate_lease(worker_id, lease_token)
        if not lease_check["ok"]:
            return lease_check
        state = _state_for_outcome(outcome)
        with self._connect() as con:
            ownership = self._validate_run_owner(con, run_id=run_id, worker_id=worker_id)
            if not ownership["ok"]:
                return ownership
            con.execute(
                """
                UPDATE runs
                SET state = ?, outcome = ?, result_payload = ?, error = ?, submitted_at = ?
                WHERE id = ? AND state = 'claimed' AND claimed_by = ?
                """,
                (state, outcome, _json(results), error, _now(), run_id, worker_id),
            )
        return {"ok": True, "accepted": True}

    def acknowledge_cancellation(
        self,
        *,
        run_id: str,
        worker_id: str,
        lease_token: str,
        partials: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        lease_check = self._validate_lease(worker_id, lease_token)
        if not lease_check["ok"]:
            return lease_check
        now = _now()
        with self._connect() as con:
            ownership = self._validate_run_owner(con, run_id=run_id, worker_id=worker_id)
            if not ownership["ok"]:
                return ownership
            con.execute(
                """
                INSERT INTO cancellation_acks(run_id, partials, received_at)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET partials=excluded.partials, received_at=excluded.received_at
                """,
                (run_id, _json(partials), now),
            )
            con.execute(
                """
                UPDATE runs
                SET state = 'cancelled', outcome = 'cancelled', result_payload = ?, submitted_at = ?
                WHERE id = ? AND state = 'claimed' AND claimed_by = ?
                """,
                (_json({"partials": partials}), now, run_id, worker_id),
            )
        return {"ok": True, "accepted": True, "partials": partials}

    def cancel_run(self, run_id: str, *, reason: str | None = None) -> dict[str, Any]:
        with self._connect() as con:
            con.execute(
                "UPDATE runs SET cancel_requested = 1, cancel_reason = ? WHERE id = ?",
                (reason, run_id),
            )
        return {"ok": True, "run": self.get_run(run_id)}

    def list_runs(self) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute("SELECT * FROM runs ORDER BY created_at, id").fetchall()
        return [_row_to_run(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as con:
            row = con.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _row_to_run(row) if row is not None else None

    def _validate_lease(self, worker_id: str, lease_token: str) -> dict[str, Any]:
        with self._connect() as con:
            lease = con.execute("SELECT * FROM leases WHERE worker_id = ?", (worker_id,)).fetchone()
            if lease is None:
                return {"ok": False, "reason": "lease_not_found"}
            if str(lease["lease_token"]) != lease_token:
                return {"ok": False, "reason": "invalid_lease_token"}
            if int(lease["expires_at"]) < _now():
                return {"ok": False, "reason": "lease_expired"}
        return {"ok": True}

    @staticmethod
    def _validate_run_owner(con: sqlite3.Connection, *, run_id: str, worker_id: str) -> dict[str, Any]:
        run = con.execute("SELECT state, claimed_by FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            return {"ok": False, "reason": "run_not_found"}
        if str(run["state"]) != "claimed":
            return {"ok": False, "reason": "run_not_claimed"}
        if str(run["claimed_by"]) != worker_id:
            return {"ok": False, "reason": "run_not_owned"}
        return {"ok": True}

    def _initialize(self) -> None:
        with self._connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    plan_name TEXT NOT NULL,
                    site TEXT NOT NULL,
                    parameters TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    cancel_reason TEXT,
                    claimed_by TEXT,
                    claimed_at INTEGER,
                    submitted_at INTEGER,
                    outcome TEXT,
                    result_payload TEXT,
                    error TEXT,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS leases (
                    worker_id TEXT PRIMARY KEY,
                    lease_token TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    last_heartbeat INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cancellation_acks (
                    run_id TEXT PRIMARY KEY,
                    partials TEXT NOT NULL,
                    received_at INTEGER NOT NULL
                );
                """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            con = sqlite3.connect(self.db_path)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            try:
                yield con
                con.commit()
            finally:
                con.close()


def _now() -> int:
    return int(time.time())


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _loads(raw: Any) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return {}


def _row_to_run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "plan_name": str(row["plan_name"]),
        "site": str(row["site"]),
        "parameters": _loads(row["parameters"]),
        "state": str(row["state"]),
        "cancel_requested": bool(row["cancel_requested"]),
        "cancel_reason": row["cancel_reason"],
        "claimed_by": row["claimed_by"],
        "claimed_at": row["claimed_at"],
        "submitted_at": row["submitted_at"],
        "outcome": row["outcome"],
        "result_payload": _loads(row["result_payload"]),
        "error": row["error"],
        "created_at": row["created_at"],
    }


def _state_for_outcome(outcome: str) -> str:
    if outcome in {"completed", "failed", "cancelled", "blocked"}:
        return outcome
    return "failed"


__all__ = ["DevServerStore"]
