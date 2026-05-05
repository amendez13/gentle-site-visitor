# mypy: disable-error-code=misc
"""FastAPI app for the SQLite-backed reference dev server."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from gsv.server.dev.store import DevServerStore

if TYPE_CHECKING:
    RequestType: TypeAlias = Request[Any]
else:
    RequestType = Request


def create_app(  # noqa: C901 - route registration is intentionally co-located for the dev API contract.
    db_path: str | Path = "data/dev-server.sqlite",
    *,
    api_key: str | None = None,
) -> FastAPI:
    """Create the reference coordination API app."""
    key = api_key if api_key is not None else os.environ.get("GSV_API_KEY", "dev")
    store = DevServerStore(db_path)
    app = FastAPI(title="Gentle Site Visitor dev server")
    app.state.store = store
    app.state.api_key = key

    async def require_api_key(
        x_api_key: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ) -> None:
        if _authorized(key, x_api_key, authorization):
            return
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/worker/lease/register", dependencies=[Depends(require_api_key)])
    async def register_lease(request: RequestType) -> dict[str, Any]:
        body = await _body(request)
        worker_id = str(body.get("worker_id") or "worker")
        ttl = int(body.get("lease_ttl_seconds") or 120)
        result = store.register_lease(worker_id=worker_id, lease_ttl_seconds=ttl)
        return cast(dict[str, Any], result)

    @app.post("/api/worker/lease/heartbeat", dependencies=[Depends(require_api_key)])
    async def heartbeat_lease(request: RequestType) -> dict[str, Any]:
        body = await _body(request)
        result = store.heartbeat(
            worker_id=str(body.get("worker_id") or ""),
            lease_token=str(body.get("lease_token") or ""),
            lease_ttl_seconds=int(body.get("lease_ttl_seconds") or 120),
        )
        return cast(dict[str, Any], result)

    @app.post("/api/worker/lease/release", dependencies=[Depends(require_api_key)])
    async def release_lease(request: RequestType) -> dict[str, Any]:
        body = await _body(request)
        result = store.release(worker_id=str(body.get("worker_id") or ""), lease_token=str(body.get("lease_token") or ""))
        return cast(dict[str, Any], result)

    @app.post("/api/runs/next/claim", dependencies=[Depends(require_api_key)])
    async def claim_next(request: RequestType) -> dict[str, Any]:
        body = await _body(request)
        result = store.claim_next(
            site=str(body.get("site") or ""),
            worker_id=str(body.get("worker_id") or ""),
            lease_token=str(body.get("lease_token") or ""),
        )
        return cast(dict[str, Any], result)

    @app.get("/api/runs/next", dependencies=[Depends(require_api_key)])
    async def get_next_run(site: str = "") -> dict[str, Any]:
        for run in store.list_runs():
            if run["state"] == "pending" and (not site or run["site"] == site):
                return {"ok": True, "run": run}
        return {"ok": True, "run": None}

    @app.post("/api/runs/{run_id}/claim", dependencies=[Depends(require_api_key)])
    async def claim_run(run_id: str, request: RequestType) -> dict[str, Any]:
        body = await _body(request)
        result = store.claim(
            run_id=run_id,
            worker_id=str(body.get("worker_id") or ""),
            lease_token=str(body.get("lease_token") or ""),
        )
        return cast(dict[str, Any], result)

    @app.get("/api/runs/{run_id}/control", dependencies=[Depends(require_api_key)])
    async def run_control(run_id: str) -> dict[str, Any]:
        result = store.control(run_id)
        return cast(dict[str, Any], result)

    @app.post("/api/runs/{run_id}/submit", dependencies=[Depends(require_api_key)])
    async def submit_run(run_id: str, request: RequestType) -> dict[str, Any]:
        body = await _body(request)
        results = body.get("results")
        result = store.submit(
            run_id=run_id,
            worker_id=str(body.get("worker_id") or ""),
            lease_token=str(body.get("lease_token") or ""),
            outcome=str(body.get("outcome") or "failed"),
            results=dict(results) if isinstance(results, dict) else {},
            error=_optional_str(body.get("error")),
        )
        return cast(dict[str, Any], result)

    @app.post("/api/runs/{run_id}/cancellation_ack", dependencies=[Depends(require_api_key)])
    async def cancellation_ack(run_id: str, request: RequestType) -> dict[str, Any]:
        body = await _body(request)
        partials = body.get("partials")
        result = store.acknowledge_cancellation(
            run_id=run_id,
            worker_id=str(body.get("worker_id") or ""),
            lease_token=str(body.get("lease_token") or ""),
            partials=_partials(partials),
        )
        return cast(dict[str, Any], result)

    @app.post("/api/runs", dependencies=[Depends(require_api_key)])
    async def create_api_run(request: RequestType) -> dict[str, Any]:
        body = await _body(request)
        return {"ok": True, "run": _create_run(store, body)}

    @app.post("/api/runs/{run_id}/heartbeat", dependencies=[Depends(require_api_key)])
    async def run_heartbeat(run_id: str, request: RequestType) -> dict[str, Any]:
        del run_id
        body = await _body(request)
        result = store.heartbeat(
            worker_id=str(body.get("worker_id") or ""),
            lease_token=str(body.get("lease_token") or ""),
            lease_ttl_seconds=int(body.get("lease_ttl_seconds") or 120),
        )
        return cast(dict[str, Any], result)

    @app.post("/api/runs/{run_id}/complete", dependencies=[Depends(require_api_key)])
    async def complete_run(run_id: str, request: RequestType) -> dict[str, Any]:
        body = await _body(request)
        body["outcome"] = "completed"
        body.setdefault("results", {})
        result_value = body.get("results")
        result = store.submit(
            run_id=run_id,
            worker_id=str(body.get("worker_id") or ""),
            lease_token=str(body.get("lease_token") or ""),
            outcome="completed",
            results=dict(result_value) if isinstance(result_value, dict) else {},
            error=None,
        )
        return cast(dict[str, Any], result)

    @app.post("/api/runs/{run_id}/fail", dependencies=[Depends(require_api_key)])
    async def fail_run(run_id: str, request: RequestType) -> dict[str, Any]:
        body = await _body(request)
        result_value = body.get("results")
        result = store.submit(
            run_id=run_id,
            worker_id=str(body.get("worker_id") or ""),
            lease_token=str(body.get("lease_token") or ""),
            outcome="failed",
            results=dict(result_value) if isinstance(result_value, dict) else {},
            error=_optional_str(body.get("error")),
        )
        return cast(dict[str, Any], result)

    @app.post("/api/runs/{run_id}/cancel", dependencies=[Depends(require_api_key)])
    async def cancel_api_run(run_id: str, request: RequestType) -> dict[str, Any]:
        body = await _body(request)
        result = store.cancel_run(run_id, reason=_optional_str(body.get("reason")))
        return cast(dict[str, Any], result)

    @app.get("/api/runs/{run_id}/status", dependencies=[Depends(require_api_key)])
    async def run_status(run_id: str) -> dict[str, Any]:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
        return {"ok": True, "run": run}

    @app.post("/admin/runs", dependencies=[Depends(require_api_key)])
    async def create_admin_run(request: RequestType) -> dict[str, Any]:
        return {"ok": True, "run": _create_run(store, await _body(request))}

    @app.post("/admin/runs/{run_id}/cancel", dependencies=[Depends(require_api_key)])
    async def cancel_admin_run(run_id: str, request: RequestType) -> dict[str, Any]:
        body = await _body(request)
        result = store.cancel_run(run_id, reason=_optional_str(body.get("reason")))
        return cast(dict[str, Any], result)

    @app.get("/admin/runs", dependencies=[Depends(require_api_key)])
    async def list_admin_runs() -> dict[str, Any]:
        return {"ok": True, "runs": store.list_runs()}

    return app


async def _body(request: RequestType) -> dict[str, Any]:
    try:
        value = await request.json()
    except Exception:
        return {}
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _authorized(expected: str, x_api_key: str | None, authorization: str | None) -> bool:
    if not expected:
        return False
    if x_api_key == expected:
        return True
    return authorization == f"Bearer {expected}"


def _create_run(store: DevServerStore, body: dict[str, Any]) -> dict[str, Any]:
    parameters = body.get("parameters")
    result = store.create_run(
        plan_name=str(body.get("plan_name") or "default"),
        site=str(body.get("site") or ""),
        parameters=dict(parameters) if isinstance(parameters, dict) else {},
    )
    return cast(dict[str, Any], result)


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _partials(value: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    for key, items in value.items():
        if isinstance(items, list):
            result[str(key)] = [dict(item) for item in items if isinstance(item, dict)]
    return cast(dict[str, Any], result)


__all__ = ["create_app"]
