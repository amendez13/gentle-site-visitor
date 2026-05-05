"""HTTP lease and run client for coordinated workers."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

LOG = logging.getLogger(__name__)

HEARTBEAT_RETRY_BACKOFF_SECONDS = (5, 15, 30)
HEARTBEAT_MAX_TRANSIENT_FAILURES = 3
HEARTBEAT_TRANSIENT_REASONS = {"transport_error", "timeout", "server_error", "temporary_unavailable", "rate_limited"}
HEARTBEAT_REREGISTER_REASONS = {"lease_expired", "lease_not_found", "lease_not_active"}
LEASE_TERMINAL_REASONS = {"invalid_lease_token"}
CLAIM_SELF_HEAL_REASONS = {"lease_expired", "lease_not_found", "lease_not_active"}


@dataclass(frozen=True)
class Run:
    """One server-coordinated unit of visit work."""

    id: str
    plan_name: str
    site: str
    parameters: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Any) -> "Run":
        """Normalize a server run payload."""
        data = value if isinstance(value, dict) else {}
        parameters = data.get("parameters")
        return cls(
            id=str(data.get("id", "")),
            plan_name=str(data.get("plan_name", "")),
            site=str(data.get("site", "")),
            parameters=dict(parameters) if isinstance(parameters, dict) else {},
        )


class LeaseClient:
    """HTTP wrapper for the worker lease and run lifecycle API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        worker_id: str | None = None,
        lease_ttl_seconds: int = 120,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:12]}"
        self.lease_token = ""
        self.lease_ttl_seconds = int(lease_ttl_seconds)
        self._http = http if http is not None else httpx.AsyncClient()
        self._owns_http = http is None

    async def register(self) -> tuple[bool, dict[str, Any]]:
        """Register or refresh this worker lease."""
        ok, payload = await self._post(
            "/api/worker/lease/register",
            {"worker_id": self.worker_id, "lease_ttl_seconds": self.lease_ttl_seconds},
        )
        if ok:
            self.worker_id = str(payload.get("worker_id") or self.worker_id)
            self.lease_token = str(payload.get("lease_token") or self.lease_token)
        return ok, payload

    async def heartbeat(self) -> tuple[bool, dict[str, Any]]:
        """Renew the active lease."""
        return await self._post(
            "/api/worker/lease/heartbeat",
            {
                "worker_id": self.worker_id,
                "lease_token": self.lease_token,
                "lease_ttl_seconds": self.lease_ttl_seconds,
            },
        )

    async def heartbeat_with_recovery(self, sleeper: Any) -> tuple[bool, dict[str, Any]]:
        """Run one heartbeat cycle with the documented backoff and re-register rules."""
        ok, payload = await self.heartbeat()
        if ok:
            return ok, payload

        reason = str(payload.get("reason", ""))
        if should_reregister(reason):
            return await self.register()
        if should_terminate(reason):
            return False, payload
        if reason not in HEARTBEAT_TRANSIENT_REASONS:
            return False, payload

        last_payload = payload
        for delay in HEARTBEAT_RETRY_BACKOFF_SECONDS:
            await sleeper(delay)
            ok, retry_payload = await self.heartbeat()
            if ok:
                return ok, retry_payload
            last_payload = retry_payload
            retry_reason = str(retry_payload.get("reason", ""))
            if should_reregister(retry_reason):
                return await self.register()
            if should_terminate(retry_reason):
                return False, retry_payload
        return False, last_payload

    async def release(self) -> tuple[bool, dict[str, Any]]:
        """Release the active lease."""
        return await self._post(
            "/api/worker/lease/release",
            {"worker_id": self.worker_id, "lease_token": self.lease_token},
        )

    async def claim_next(self, *, site: str) -> Run | None:
        """Claim the next pending run for one site."""
        ok, payload = await self._post(
            "/api/runs/next/claim",
            {"worker_id": self.worker_id, "lease_token": self.lease_token, "site": site},
        )
        if not ok:
            reason = str(payload.get("reason", ""))
            if reason in CLAIM_SELF_HEAL_REASONS:
                LOG.info("Claim failed due to stale lease state: %s", reason)
            return None
        run = payload.get("run")
        return Run.from_mapping(run) if isinstance(run, dict) else None

    async def claim(self, run_id: str) -> Run | None:
        """Claim a specific run id."""
        ok, payload = await self._post(
            f"/api/runs/{run_id}/claim",
            {"worker_id": self.worker_id, "lease_token": self.lease_token},
        )
        run = payload.get("run") if ok else None
        return Run.from_mapping(run) if isinstance(run, dict) else None

    async def submit(
        self,
        run_id: str,
        *,
        outcome: str,
        results: dict[str, Any],
        error: str | None = None,
    ) -> bool:
        """Submit a terminal run outcome."""
        ok, _payload = await self._post(
            f"/api/runs/{run_id}/submit",
            {
                "worker_id": self.worker_id,
                "lease_token": self.lease_token,
                "outcome": outcome,
                "results": results,
                "error": error,
            },
        )
        return ok

    async def acknowledge_cancellation(self, run_id: str, *, partials: dict[str, list[dict[str, Any]]]) -> bool:
        """Acknowledge cooperative cancellation with drained partial results."""
        ok, _payload = await self._post(
            f"/api/runs/{run_id}/cancellation_ack",
            {
                "worker_id": self.worker_id,
                "lease_token": self.lease_token,
                "partials": partials,
            },
        )
        return ok

    async def aclose(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_http:
            await self._http.aclose()

    async def _post(self, path: str, payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        try:
            response = await self._http.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=_auth_headers(self.api_key),
            )
            invalid_json = False
            if response.content:
                try:
                    data = response.json()
                except ValueError:
                    data = {}
                    invalid_json = True
            else:
                data = {}
            if not isinstance(data, dict):
                data = {}
                invalid_json = True
            if invalid_json:
                data.setdefault("reason", "server_error" if response.status_code >= 500 else "invalid_response")
                return False, data
            if response.status_code >= 500:
                data.setdefault("reason", "server_error")
                return False, data
            if response.status_code >= 400:
                data.setdefault("reason", "request_failed")
                return False, data
            return bool(data.get("ok", True)), data
        except (httpx.TimeoutException, httpx.TransportError):
            LOG.debug("Lease API request failed: %s", path, exc_info=True)
            return False, {"ok": False, "reason": "transport_error"}


def should_reregister(reason: str) -> bool:
    """Return whether a heartbeat/claim reason should refresh the lease."""
    return reason in HEARTBEAT_REREGISTER_REASONS


def should_terminate(reason: str) -> bool:
    """Return whether a lease failure is terminal for this worker."""
    return reason in LEASE_TERMINAL_REASONS


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"} if api_key else {}


__all__ = [
    "CLAIM_SELF_HEAL_REASONS",
    "HEARTBEAT_MAX_TRANSIENT_FAILURES",
    "HEARTBEAT_REREGISTER_REASONS",
    "HEARTBEAT_RETRY_BACKOFF_SECONDS",
    "HEARTBEAT_TRANSIENT_REASONS",
    "LEASE_TERMINAL_REASONS",
    "LeaseClient",
    "Run",
    "should_reregister",
    "should_terminate",
]
