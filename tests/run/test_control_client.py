"""Tests for the run control HTTP client."""

from __future__ import annotations

import httpx

from gsv.run import ControlClient


async def test_control_client_returns_payload_and_none_on_errors() -> None:
    """Control polling normalizes success and transient failures."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"cancel_requested": True, "cancel_reason": "operator"})
        raise httpx.ConnectError("offline", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://testserver")
    client = ControlClient("http://testserver", "secret", http=http)

    payload = await client.get_run_control("run-1")
    missing = await client.get_run_control("run-1")

    assert payload == {"cancel_requested": True, "cancel_reason": "operator"}
    assert missing is None
    await http.aclose()


async def test_control_client_owned_close() -> None:
    """Owned clients can be closed through the public API."""
    client = ControlClient("http://testserver", "secret")

    await client.aclose()
