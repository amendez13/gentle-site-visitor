"""End-to-end S7 worker/dev-server tests using the ASGI app in process."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx

from gsv.config import PacingConfig, SiteAuthConfig, SiteConfig, VisitorConfig
from gsv.run import ControlClient, LeaseClient, RunController
from gsv.server.dev import create_app
from gsv.session import SiteAuthAdapter
from gsv.visit import StepResult, VisitContext, VisitPlan
from tests.run.test_controller import FakeBrowser, FakeSession


class CompleteStep:
    """Small successful integration step."""

    name = "complete"
    content_marker = None

    async def execute(self, ctx: VisitContext) -> StepResult:
        ctx.extracted["items"] = [{"id": "done"}]
        return StepResult(name=self.name, outcome="ok")


class CancelAfterWorkStep:
    """Step that asks the server to cancel before the runner's post boundary."""

    name = "cancel_after_work"
    content_marker = None

    def __init__(self, client: httpx.AsyncClient, run_id: str) -> None:
        self.client = client
        self.run_id = run_id

    async def execute(self, ctx: VisitContext) -> StepResult:
        ctx.extracted["items"] = [{"id": "partial"}]
        await self.client.post(f"/admin/runs/{self.run_id}/cancel", json={"reason": "operator"})
        return StepResult(name=self.name, outcome="ok")


async def test_worker_completes_run_against_dev_server(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A controller can claim from the dev server, execute, and submit success."""
    app = create_app(tmp_path / "dev.sqlite", api_key="secret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers={"X-API-Key": "secret"}) as http:
        created = await http.post("/admin/runs", json={"plan_name": "default", "site": "example"})
        run_id = created.json()["run"]["id"]
        controller = _controller(
            http=http,
            plan_factory=lambda ctx: VisitPlan(steps=[CompleteStep()]),
        )

        code = await controller.run_once()
        status = await http.get(f"/api/runs/{run_id}/status")

    assert code == 0
    assert status.json()["run"]["state"] == "completed"
    assert status.json()["run"]["result_payload"] == {"items": [{"id": "done"}]}


async def test_worker_acknowledges_cancellation_against_dev_server(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A server-side cancel request stops at the next boundary and stores partials."""
    app = create_app(tmp_path / "dev.sqlite", api_key="secret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers={"X-API-Key": "secret"}) as http:
        created = await http.post("/admin/runs", json={"plan_name": "default", "site": "example"})
        run_id = created.json()["run"]["id"]
        controller = _controller(
            http=http,
            plan_factory=lambda ctx: VisitPlan(steps=[CancelAfterWorkStep(http, run_id)]),
        )

        code = await controller.run_once()
        status = await http.get(f"/api/runs/{run_id}/status")

    assert code == 0
    assert status.json()["run"]["state"] == "cancelled"
    assert status.json()["run"]["result_payload"] == {"partials": {"extracted": [{"items": [{"id": "partial"}]}]}}


def _controller(*, http: httpx.AsyncClient, plan_factory: Any) -> RunController:
    base = VisitorConfig()
    visitor = replace(
        base, observability=replace(base.observability, mode="off"), pacing=replace(PacingConfig(), profile="disabled")
    )
    site = SiteConfig(name="example", auth=SiteAuthConfig(auth_marker_url="https://example.test/"))
    adapter = SiteAuthAdapter.from_config(site.auth)
    return RunController(
        site="example",
        config=visitor,
        site_config=site,
        site_adapter=adapter,
        plan_factory=plan_factory,
        lease_client=LeaseClient("http://testserver", "secret", worker_id="worker-1", http=http),
        control_client=ControlClient("http://testserver", "secret", http=http),
        browser_factory=FakeBrowser,  # type: ignore[arg-type]
        session_factory=FakeSession,  # type: ignore[arg-type]
        cancellation_min_poll_interval_seconds=0,
    )
