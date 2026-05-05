"""HTTP client for run-control polling."""

from __future__ import annotations

import logging
from typing import Any

import httpx

LOG = logging.getLogger(__name__)


class ControlClient:
    """Read cooperative run-control state from the coordination API."""

    def __init__(self, base_url: str, api_key: str, *, http: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._http = http if http is not None else httpx.AsyncClient()
        self._owns_http = http is None

    async def get_run_control(self, run_id: str) -> dict[str, Any] | None:
        """Return control state for a run, or ``None`` on transient failures."""
        try:
            response = await self._http.get(
                f"{self.base_url}/api/runs/{run_id}/control",
                headers=_auth_headers(self.api_key),
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            LOG.debug("Run control poll failed for run %s", run_id, exc_info=True)
            return None
        return payload if isinstance(payload, dict) else None

    async def aclose(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_http:
            await self._http.aclose()


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"} if api_key else {}


__all__ = ["ControlClient"]
