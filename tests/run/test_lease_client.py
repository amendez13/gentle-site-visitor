"""Tests for S7 lease client invariants."""

from __future__ import annotations

import json
from typing import Any

import httpx

from gsv.run import HEARTBEAT_RETRY_BACKOFF_SECONDS, LeaseClient, should_reregister, should_terminate


def test_heartbeat_backoff_tuple_is_load_bearing() -> None:
    """The heartbeat retry tuple must remain numerically identical to CE."""
    assert HEARTBEAT_RETRY_BACKOFF_SECONDS == (5, 15, 30)


def test_lease_reason_classification() -> None:
    """Lease failure reasons drive controller recovery behavior."""
    assert should_reregister("lease_expired")
    assert should_reregister("lease_not_found")
    assert should_terminate("invalid_lease_token")


async def test_heartbeat_with_recovery_uses_backoff_sequence() -> None:
    """Transient heartbeat failures are retried with the documented sequence."""
    client = LeaseClient("http://example.test", "key")
    payloads = [
        (False, {"reason": "transport_error"}),
        (False, {"reason": "transport_error"}),
        (True, {"ok": True}),
    ]
    delays: list[float] = []

    async def heartbeat() -> tuple[bool, dict[str, Any]]:
        return payloads.pop(0)

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    client.heartbeat = heartbeat  # type: ignore[method-assign]

    ok, payload = await client.heartbeat_with_recovery(sleeper)

    assert ok
    assert payload == {"ok": True}
    assert delays == [5, 15]
    await client.aclose()


async def test_heartbeat_reregisters_on_expired_lease() -> None:
    """Expired lease responses trigger registration."""
    client = LeaseClient("http://example.test", "key")
    registered = False

    async def heartbeat() -> tuple[bool, dict[str, Any]]:
        return False, {"reason": "lease_expired"}

    async def register() -> tuple[bool, dict[str, Any]]:
        nonlocal registered
        registered = True
        return True, {"ok": True, "lease_token": "new"}

    async def sleeper(delay: float) -> None:
        del delay

    client.heartbeat = heartbeat  # type: ignore[method-assign]
    client.register = register  # type: ignore[method-assign]

    ok, _payload = await client.heartbeat_with_recovery(sleeper)

    assert ok
    assert registered
    await client.aclose()


async def test_lease_client_http_paths_cover_claim_submit_and_failures() -> None:
    """The HTTP wrapper normalizes success, request failure, server failure, and transport errors."""
    requests: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8")) if request.content else {}
        requests.append((request.url.path, dict(request.headers), dict(payload)))
        if request.url.path == "/api/worker/lease/register":
            return httpx.Response(200, json={"ok": True, "worker_id": "worker-1", "lease_token": "token"})
        if request.url.path == "/api/worker/lease/heartbeat":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/runs/run-1/claim":
            return httpx.Response(
                200,
                json={"ok": True, "run": {"id": "run-1", "plan_name": "default", "site": "example", "parameters": {}}},
            )
        if request.url.path == "/api/runs":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "run": {
                        "id": "created-1",
                        "plan_name": "morning",
                        "site": "example",
                        "parameters": {"profile_id": "morning"},
                    },
                },
            )
        if request.url.path == "/api/runs/next/claim":
            return httpx.Response(409, json={"ok": False, "reason": "lease_expired"})
        if request.url.path == "/api/runs/run-1/submit":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/runs/run-1/cancellation_ack":
            return httpx.Response(500, json={"ok": False})
        if request.url.path == "/api/worker/lease/release":
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(404, json={"ok": False})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://testserver")
    client = LeaseClient("http://testserver", "secret", http=http)

    registered, _payload = await client.register()
    heartbeat_ok, _heartbeat_payload = await client.heartbeat()
    claimed = await client.claim("run-1")
    created = await client.create_run(site="example", plan_name="morning", profile_id="morning")
    next_run = await client.claim_next(site="example")
    submitted = await client.submit("run-1", outcome="completed", results={})
    acked = await client.acknowledge_cancellation("run-1", partials={})
    released, release_payload = await client.release()

    assert registered
    assert heartbeat_ok
    assert claimed is not None and claimed.id == "run-1"
    assert created is not None and created.id == "created-1"
    assert created.parameters == {"profile_id": "morning"}
    assert next_run is None
    assert submitted
    assert not acked
    assert not released
    assert release_payload["reason"] == "transport_error"
    assert requests[0][1]["x-api-key"] == "secret"
    assert requests[1][2]["lease_ttl_seconds"] == 120
    await http.aclose()


async def test_lease_client_normalizes_non_json_responses() -> None:
    """Non-JSON API bodies stay in the structured failure path."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/worker/lease/heartbeat":
            return httpx.Response(502, content=b"bad gateway")
        return httpx.Response(200, content=b"<html>not json</html>")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://testserver")
    client = LeaseClient("http://testserver", "secret", http=http)

    heartbeat_ok, heartbeat_payload = await client.heartbeat()
    submit_ok = await client.submit("run-1", outcome="completed", results={})

    assert not heartbeat_ok
    assert heartbeat_payload["reason"] == "server_error"
    assert not submit_ok
    await http.aclose()
