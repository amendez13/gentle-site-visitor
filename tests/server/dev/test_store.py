"""Direct tests for dev-server SQLite store edge cases."""

from __future__ import annotations

import sqlite3

from gsv.server.dev.store import DevServerStore, _loads


def test_store_lease_and_claim_failure_branches(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Store branches report precise reasons for stale or invalid state."""
    store = DevServerStore(tmp_path / "dev.sqlite")
    run = store.create_run(plan_name="default", site="example")

    assert store.heartbeat(worker_id="missing", lease_token="token") == {"ok": False, "reason": "lease_not_found"}
    lease = store.register_lease(worker_id="worker-1", lease_ttl_seconds=120)
    assert store.heartbeat(worker_id="worker-1", lease_token="bad") == {"ok": False, "reason": "invalid_lease_token"}
    assert store.claim_next(site="example", worker_id="worker-1", lease_token="bad") == {
        "ok": False,
        "reason": "invalid_lease_token",
    }
    assert store.claim(run_id="missing", worker_id="worker-1", lease_token=lease["lease_token"]) == {
        "ok": False,
        "reason": "run_not_found",
    }

    claimed = store.claim(run_id=run["id"], worker_id="worker-1", lease_token=lease["lease_token"])
    assert claimed["ok"] is True
    assert store.claim(run_id=run["id"], worker_id="worker-1", lease_token=lease["lease_token"])["ok"] is True
    lease_2 = store.register_lease(worker_id="worker-2", lease_ttl_seconds=120)
    assert store.claim(run_id=run["id"], worker_id="worker-2", lease_token=lease_2["lease_token"]) == {
        "ok": False,
        "reason": "run_already_claimed",
    }
    assert store.submit(
        run_id=run["id"],
        worker_id="worker-2",
        lease_token=lease_2["lease_token"],
        outcome="completed",
        results={},
        error=None,
    ) == {"ok": False, "reason": "run_not_owned"}
    assert store.acknowledge_cancellation(
        run_id=run["id"],
        worker_id="worker-2",
        lease_token=lease_2["lease_token"],
        partials={},
    ) == {"ok": False, "reason": "run_not_owned"}
    assert store.claim_next(site="example", worker_id="worker-1", lease_token=lease["lease_token"]) == {
        "ok": True,
        "run": None,
    }
    assert store.submit(
        run_id=run["id"],
        worker_id="worker-1",
        lease_token=lease["lease_token"],
        outcome="weird",
        results={},
        error=None,
    ) == {"ok": True, "accepted": True}
    assert store.claim(run_id=run["id"], worker_id="worker-1", lease_token=lease["lease_token"]) == {
        "ok": False,
        "reason": "run_not_claimable",
    }
    assert store.claim(run_id=run["id"], worker_id="worker-1", lease_token="bad") == {
        "ok": False,
        "reason": "invalid_lease_token",
    }
    assert store.submit(
        run_id=run["id"],
        worker_id="worker-1",
        lease_token="bad",
        outcome="failed",
        results={},
        error=None,
    ) == {"ok": False, "reason": "invalid_lease_token"}

    unclaimed = store.create_run(plan_name="default", site="example")
    assert store.submit(
        run_id=unclaimed["id"],
        worker_id="worker-1",
        lease_token=lease["lease_token"],
        outcome="completed",
        results={},
        error=None,
    ) == {"ok": False, "reason": "run_not_claimed"}
    assert store.acknowledge_cancellation(
        run_id=unclaimed["id"],
        worker_id="worker-1",
        lease_token=lease["lease_token"],
        partials={},
    ) == {"ok": False, "reason": "run_not_claimed"}
    assert store.acknowledge_cancellation(
        run_id=run["id"],
        worker_id="worker-1",
        lease_token="bad",
        partials={},
    ) == {"ok": False, "reason": "invalid_lease_token"}


def test_store_expired_lease_and_json_fallbacks(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Expired leases and malformed JSON are normalized predictably."""
    store = DevServerStore(tmp_path / "dev.sqlite")
    lease = store.register_lease(worker_id="worker-1", lease_ttl_seconds=1)
    with store._connect() as con:
        con.execute("UPDATE leases SET expires_at = 0 WHERE worker_id = ?", ("worker-1",))

    assert store.heartbeat(worker_id="worker-1", lease_token=lease["lease_token"]) == {
        "ok": False,
        "reason": "lease_expired",
    }
    assert store.control("missing") == {"cancel_requested": False, "cancel_reason": None}
    assert _loads("") == {}
    assert _loads("{not-json") == {}

    row = sqlite3.Row
    assert row is not None
