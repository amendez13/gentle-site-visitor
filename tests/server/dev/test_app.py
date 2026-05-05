"""Tests for the reference dev server contract."""

from __future__ import annotations

import httpx

from gsv.server.dev import create_app


async def test_dev_server_requires_api_key(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The dev server is not open even in local mode."""
    transport = httpx.ASGITransport(app=create_app(tmp_path / "dev.sqlite", api_key="secret"))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/admin/runs", json={"plan_name": "default", "site": "example"})

    assert response.status_code == 401


async def test_dev_server_run_lifecycle_and_cancellation_ack(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Register, claim, heartbeat, cancel, acknowledge, and inspect a run."""
    transport = httpx.ASGITransport(app=create_app(tmp_path / "dev.sqlite", api_key="secret"))
    headers = {"X-API-Key": "secret"}
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers=headers) as client:
        created = await client.post(
            "/admin/runs",
            json={"plan_name": "default", "site": "example", "parameters": {"profile": "demo"}},
        )
        run = created.json()["run"]
        registered = await client.post(
            "/api/worker/lease/register",
            json={"worker_id": "worker-1", "lease_ttl_seconds": 120},
        )
        lease_token = registered.json()["lease_token"]
        claimed = await client.post(
            "/api/runs/next/claim",
            json={"worker_id": "worker-1", "lease_token": lease_token, "site": "example"},
        )
        heartbeat = await client.post(
            f"/api/runs/{run['id']}/heartbeat",
            json={"worker_id": "worker-1", "lease_token": lease_token},
        )
        await client.post(f"/admin/runs/{run['id']}/cancel", json={"reason": "operator"})
        control = await client.get(f"/api/runs/{run['id']}/control")
        ack = await client.post(
            f"/api/runs/{run['id']}/cancellation_ack",
            json={"worker_id": "worker-1", "lease_token": lease_token, "partials": {"items": [{"id": "1"}]}},
        )
        status = await client.get(f"/api/runs/{run['id']}/status")

    assert created.status_code == 200
    assert claimed.json()["run"]["id"] == run["id"]
    assert heartbeat.json()["ok"] is True
    assert control.json() == {"cancel_requested": True, "cancel_reason": "operator"}
    assert ack.json()["accepted"] is True
    assert status.json()["run"]["state"] == "cancelled"
    assert status.json()["run"]["result_payload"] == {"partials": {"items": [{"id": "1"}]}}


async def test_dev_server_compatibility_endpoints(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The issue-listed compatibility endpoints expose create/status/complete/fail/cancel flows."""
    transport = httpx.ASGITransport(app=create_app(tmp_path / "dev.sqlite", api_key="secret"))
    headers = {"Authorization": "Bearer secret"}
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers=headers) as client:
        health = await client.get("/healthz")
        created = await client.post("/api/runs", json={"profile_id": "morning", "site": "example"})
        run_id = created.json()["run"]["id"]
        next_run = await client.get("/api/runs/next?site=example")
        missing = await client.get("/api/runs/missing/status")
        registered = await client.post("/api/worker/lease/register", json={"worker_id": "worker-1"})
        lease_token = registered.json()["lease_token"]
        await client.post(
            f"/api/runs/{run_id}/claim",
            json={"worker_id": "worker-1", "lease_token": lease_token},
        )
        complete = await client.post(
            f"/api/runs/{run_id}/complete",
            json={"worker_id": "worker-1", "lease_token": lease_token, "results": {"ok": True}},
        )
        failed_run = await client.post("/api/runs", json={"plan_name": "default", "site": "example"})
        failed_id = failed_run.json()["run"]["id"]
        await client.post(
            f"/api/runs/{failed_id}/claim",
            json={"worker_id": "worker-1", "lease_token": lease_token},
        )
        fail = await client.post(
            f"/api/runs/{failed_id}/fail",
            json={"worker_id": "worker-1", "lease_token": lease_token, "results": {"ok": False}, "error": "boom"},
        )
        cancel = await client.post(f"/api/runs/{failed_id}/cancel", json={"reason": "operator"})
        listed = await client.get("/admin/runs")

    assert health.json() == {"status": "ok"}
    assert created.json()["run"]["plan_name"] == "morning"
    assert created.json()["run"]["parameters"]["profile_id"] == "morning"
    assert next_run.json()["run"]["id"] == run_id
    assert missing.status_code == 404
    assert complete.json()["accepted"] is True
    assert fail.json()["accepted"] is True
    assert cancel.json()["run"]["cancel_requested"] is True
    assert len(listed.json()["runs"]) == 2


async def test_dev_server_edge_routes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Compatibility routes normalize empty queues, direct claims, malformed bodies, and bad partials."""
    transport = httpx.ASGITransport(app=create_app(tmp_path / "dev.sqlite", api_key="secret"))
    headers = {"X-API-Key": "secret"}
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers=headers) as client:
        empty_next = await client.get("/api/runs/next?site=missing")
        malformed = await client.post("/api/runs", content=b"{not-json", headers={"X-API-Key": "secret"})
        run_id = malformed.json()["run"]["id"]
        lease = await client.post("/api/worker/lease/register", json={"worker_id": "worker-1"})
        lease_token = lease.json()["lease_token"]
        claimed = await client.post(
            f"/api/runs/{run_id}/claim",
            json={"worker_id": "worker-1", "lease_token": lease_token},
        )
        ack = await client.post(
            f"/api/runs/{run_id}/cancellation_ack",
            json={"worker_id": "worker-1", "lease_token": lease_token, "partials": []},
        )

    assert empty_next.json() == {"ok": True, "run": None}
    assert malformed.json()["run"]["plan_name"] == "default"
    assert claimed.json()["run"]["id"] == run_id
    assert ack.json()["partials"] == {}
