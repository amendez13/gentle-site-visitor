"""Tests for S7 RunController behavior."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from gsv.browser import RateLimiter
from gsv.config import PacingConfig, SiteAuthConfig, SiteConfig, VisitorConfig
from gsv.run import EXIT_AUTH_FAILURE, EXIT_OK, EXIT_RUNTIME_ERROR, ControlClient, Run, RunController
from gsv.session import SiteAuthAdapter
from gsv.visit import StepResult, VisitContext, VisitPlan


class FakeLeaseClient:
    """Lease-client double that records terminal submissions."""

    def __init__(self, run: Run | None, *, submit_ok: bool = True, ack_ok: bool = True) -> None:
        self.run = run
        self.submit_ok = submit_ok
        self.ack_ok = ack_ok
        self.submissions: list[dict[str, Any]] = []
        self.cancellations: list[dict[str, Any]] = []
        self.released = False

    async def register(self) -> tuple[bool, dict[str, Any]]:
        return True, {"ok": True}

    async def claim_next(self, *, site: str) -> Run | None:
        del site
        run = self.run
        self.run = None
        return run

    async def heartbeat_with_recovery(self, sleeper: Any) -> tuple[bool, dict[str, Any]]:
        del sleeper
        return True, {"ok": True}

    async def release(self) -> tuple[bool, dict[str, Any]]:
        self.released = True
        return True, {"ok": True}

    async def submit(
        self,
        run_id: str,
        *,
        outcome: str,
        results: dict[str, Any],
        error: str | None = None,
    ) -> bool:
        self.submissions.append({"run_id": run_id, "outcome": outcome, "results": results, "error": error})
        return self.submit_ok

    async def acknowledge_cancellation(self, run_id: str, *, partials: dict[str, list[dict[str, Any]]]) -> bool:
        self.cancellations.append({"run_id": run_id, "partials": partials})
        return self.ack_ok


class FakeControlClient(ControlClient):
    """Control-client double with queued control payloads."""

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = list(payloads)

    async def get_run_control(self, run_id: str) -> dict[str, Any] | None:
        del run_id
        return self.payloads.pop(0) if self.payloads else {"cancel_requested": False, "cancel_reason": None}


class FakeBrowser:
    """BrowserManager double for controller tests."""

    def __init__(self, visitor_config: VisitorConfig, site_config: SiteConfig, **kwargs: Any) -> None:
        del kwargs
        self.visitor = visitor_config
        self.site = site_config
        self.rate_limiter = RateLimiter(max_per_hour=999)

    def get_browser_metadata(self) -> dict[str, Any]:
        return {"chromium_version": "fake", "headless": True, "viewport": {"width": 100, "height": 100}}

    def attach_recorder(self, recorder: Any) -> None:
        del recorder

    async def start_tracing(self) -> None:
        pass

    async def stop_tracing(self) -> None:
        pass

    async def enable_har_for_session(self) -> None:
        pass

    async def finalize_har(self) -> None:
        pass

    def finalize_video(self) -> None:
        pass


class FakeSession:
    """Successful session double."""

    def __init__(self, browser: FakeBrowser, adapter: SiteAuthAdapter, config: VisitorConfig, **kwargs: Any) -> None:
        del adapter, config, kwargs
        self.browser = browser

    async def start(self) -> bool:
        return True

    async def login(self, credentials: Any = None) -> bool:
        del credentials
        return True

    async def post_login_warmup(self) -> bool:
        return False

    async def new_page(self) -> object:
        return object()

    async def close(self) -> None:
        pass


class FailingAuthSession(FakeSession):
    """Authentication failure session double."""

    async def start(self) -> bool:
        return False

    async def login(self, credentials: Any = None) -> bool:
        del credentials
        return False


class SetupAuthErrorSession(FakeSession):
    """Session double that raises during restore."""

    async def start(self) -> bool:
        from gsv.session import SessionAuthError

        raise SessionAuthError("setup failed")


class ExtractStep:
    """Step that leaves partial extracted state behind."""

    name = "extract"
    content_marker = None

    async def execute(self, ctx: VisitContext) -> StepResult:
        ctx.extracted["items"] = [{"id": "1"}]
        return StepResult(name=self.name, outcome="ok")


def build_plan(ctx: VisitContext) -> VisitPlan:
    del ctx
    return VisitPlan(steps=[ExtractStep()])


def _controller(
    lease: FakeLeaseClient,
    control: FakeControlClient,
    *,
    session_factory: Any = FakeSession,
) -> RunController:
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
        plan_factory=build_plan,
        lease_client=lease,  # type: ignore[arg-type]
        control_client=control,
        browser_factory=FakeBrowser,  # type: ignore[arg-type]
        session_factory=session_factory,  # type: ignore[arg-type]
        cancellation_min_poll_interval_seconds=0,
    )


async def test_controller_run_once_submits_completed_and_releases() -> None:
    """Completed visits submit their extracted result and release the lease."""
    lease = FakeLeaseClient(Run(id="run-1", plan_name="default", site="example"))
    controller = _controller(lease, FakeControlClient([]))

    code = await controller.run_once()

    assert code == EXIT_OK
    assert lease.submissions == [
        {"run_id": "run-1", "outcome": "completed", "results": {"items": [{"id": "1"}]}, "error": None}
    ]
    assert lease.released


async def test_controller_run_once_without_claim_releases_successfully() -> None:
    """An empty queue is a clean one-shot worker exit."""
    lease = FakeLeaseClient(None)
    controller = _controller(lease, FakeControlClient([]))

    code = await controller.run_once()

    assert code == EXIT_OK
    assert lease.released


async def test_controller_register_failure_exits_runtime_without_release() -> None:
    """Registration failures are restartable runtime failures."""
    lease = FakeLeaseClient(None)

    async def register() -> tuple[bool, dict[str, Any]]:
        return False, {"reason": "server_error"}

    lease.register = register  # type: ignore[method-assign]
    controller = _controller(lease, FakeControlClient([]))

    code = await controller.run_once()

    assert code == EXIT_RUNTIME_ERROR
    assert not lease.released


async def test_controller_cancellation_acknowledges_partials_and_continues_cleanly() -> None:
    """Cancellation at a post-step boundary sends drained partials."""
    lease = FakeLeaseClient(Run(id="run-1", plan_name="default", site="example"))
    controller = _controller(
        lease,
        FakeControlClient(
            [
                {"cancel_requested": False, "cancel_reason": None},
                {"cancel_requested": True, "cancel_reason": "operator"},
            ]
        ),
    )

    code = await controller.run_once()

    assert code == EXIT_OK
    assert lease.cancellations == [{"run_id": "run-1", "partials": {"extracted": [{"items": [{"id": "1"}]}]}}]
    assert lease.released


async def test_controller_submit_failure_exits_runtime() -> None:
    """A rejected terminal submission is a restartable runtime failure."""
    lease = FakeLeaseClient(Run(id="run-1", plan_name="default", site="example"), submit_ok=False)
    controller = _controller(lease, FakeControlClient([]))

    code = await controller.run_once()

    assert code == EXIT_RUNTIME_ERROR
    assert lease.submissions == [
        {"run_id": "run-1", "outcome": "completed", "results": {"items": [{"id": "1"}]}, "error": None}
    ]
    assert lease.released


async def test_controller_cancellation_ack_failure_exits_runtime() -> None:
    """A rejected cancellation acknowledgement does not report success."""
    lease = FakeLeaseClient(Run(id="run-1", plan_name="default", site="example"), ack_ok=False)
    controller = _controller(
        lease,
        FakeControlClient(
            [
                {"cancel_requested": False, "cancel_reason": None},
                {"cancel_requested": True, "cancel_reason": "operator"},
            ]
        ),
    )

    code = await controller.run_once()

    assert code == EXIT_RUNTIME_ERROR
    assert lease.cancellations == [{"run_id": "run-1", "partials": {"extracted": [{"items": [{"id": "1"}]}]}}]
    assert lease.released


async def test_controller_auth_failure_exits_10() -> None:
    """Authentication failures map to the documented no-restart exit code."""
    lease = FakeLeaseClient(Run(id="run-1", plan_name="default", site="example"))
    controller = _controller(lease, FakeControlClient([]), session_factory=FailingAuthSession)

    code = await controller.run_once()

    assert code == EXIT_AUTH_FAILURE
    assert lease.submissions[0]["outcome"] == "blocked"


async def test_controller_session_auth_error_exits_10_at_boundary() -> None:
    """Auth setup exceptions also map to the auth boundary code."""
    lease = FakeLeaseClient(Run(id="run-1", plan_name="default", site="example"))
    controller = _controller(lease, FakeControlClient([]), session_factory=SetupAuthErrorSession)

    code = await controller.run_once()

    assert code == EXIT_AUTH_FAILURE
    assert lease.released


async def test_controller_runtime_failure_exits_1() -> None:
    """Runtime exceptions map to restartable failure."""

    def failing_plan(ctx: VisitContext) -> VisitPlan:
        del ctx
        raise RuntimeError("app failed")

    lease = FakeLeaseClient(Run(id="run-1", plan_name="default", site="example"))
    controller = _controller(lease, FakeControlClient([]))
    object.__setattr__(controller, "plan_factory", failing_plan)

    code = await controller.run_once()

    assert code == EXIT_RUNTIME_ERROR
    assert lease.submissions[0]["outcome"] == "failed"


async def test_controller_visit_key_error_exits_runtime() -> None:
    """Post-auth app KeyErrors stay in the restartable runtime-failure bucket."""

    def failing_plan(ctx: VisitContext) -> VisitPlan:
        del ctx
        raise KeyError("app bug")

    lease = FakeLeaseClient(Run(id="run-1", plan_name="default", site="example"))
    controller = _controller(lease, FakeControlClient([]))
    object.__setattr__(controller, "plan_factory", failing_plan)

    code = await controller.run_once()

    assert code == EXIT_RUNTIME_ERROR
    assert lease.submissions[0]["outcome"] == "failed"


async def test_controller_heartbeat_failure_exits_runtime_and_releases() -> None:
    """A failed heartbeat handle stops idle polling."""
    lease = FakeLeaseClient(None)
    controller = _controller(lease, FakeControlClient([]))
    heartbeat_handle: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    heartbeat_handle.set_exception(RuntimeError("heartbeat failed: invalid_lease_token"))

    def start_heartbeat() -> asyncio.Future[None]:
        return heartbeat_handle

    object.__setattr__(controller, "_start_heartbeat", start_heartbeat)

    code = await controller.run_forever(poll_interval_seconds=1)

    assert code == EXIT_RUNTIME_ERROR
    assert lease.released


async def test_controller_execute_guard_cancels_when_heartbeat_fails() -> None:
    """A heartbeat failure wins over in-progress execution."""
    lease = FakeLeaseClient(None)
    controller = _controller(lease, FakeControlClient([]))
    heartbeat_handle: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    heartbeat_handle.set_exception(RuntimeError("heartbeat failed: lease_expired"))

    async def slow_execute(run: Run) -> int:
        del run
        await asyncio.sleep(60)
        return int(EXIT_OK)

    object.__setattr__(controller, "_execute", slow_execute)

    with pytest.raises(RuntimeError, match="lease_expired"):
        await controller._execute_with_heartbeat_guard(Run(id="run-1", plan_name="default", site="example"), heartbeat_handle)


async def test_controller_sleep_guard_handles_completion_and_heartbeat_failure() -> None:
    """Idle polling observes heartbeat failure without blocking normal short sleeps."""
    lease = FakeLeaseClient(None)
    controller = _controller(lease, FakeControlClient([]))
    heartbeat_ok: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    await controller._sleep_with_heartbeat_guard(0, heartbeat_ok)

    heartbeat_failed: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    heartbeat_failed.set_exception(RuntimeError("heartbeat failed: invalid_lease_token"))

    with pytest.raises(RuntimeError, match="invalid_lease_token"):
        await controller._sleep_with_heartbeat_guard(60, heartbeat_failed)


async def test_controller_heartbeat_helpers_cover_terminal_states() -> None:
    """Heartbeat helpers normalize pending, cancelled, and cleanly stopped handles."""
    pending: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    RunController._raise_if_heartbeat_failed(pending)

    cancelled: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    cancelled.cancel()
    RunController._raise_if_heartbeat_failed(cancelled)
    await RunController._stop_heartbeat(cancelled)

    stopped: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    stopped.set_result(None)
    with pytest.raises(RuntimeError, match="heartbeat stopped"):
        RunController._raise_if_heartbeat_failed(stopped)


async def test_controller_run_forever_exits_on_auth_failure_and_releases() -> None:
    """The long-running loop exits immediately on auth failure."""
    lease = FakeLeaseClient(Run(id="run-1", plan_name="default", site="example"))
    controller = _controller(lease, FakeControlClient([]), session_factory=FailingAuthSession)

    code = await controller.run_forever(poll_interval_seconds=1)

    assert code == EXIT_AUTH_FAILURE
    assert lease.released
