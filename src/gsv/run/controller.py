"""Run controller that coordinates lease, session, visit execution, and cancellation."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from gsv import apps
from gsv.apps import PlanFactory
from gsv.browser import BrowserManager
from gsv.config import SiteConfig, VisitorConfig
from gsv.observability import RunRef, SessionRecorder
from gsv.pacing import build_pacing
from gsv.run.cancellation import CancellationMonitor, RunCancellationRequested
from gsv.run.control_client import ControlClient
from gsv.run.exit_codes import EXIT_AUTH_FAILURE, EXIT_OK, EXIT_RUNTIME_ERROR
from gsv.run.lease_client import LeaseClient, Run
from gsv.session import Credentials, Session, SessionAuthError, SiteAuthAdapter
from gsv.visit import VisitContext, VisitResult
from gsv.visit.runner import VisitRunner

LOG = logging.getLogger(__name__)

BrowserFactory = Callable[..., BrowserManager]
SessionFactory = Callable[..., Session]
RecorderFactory = Callable[..., SessionRecorder | None]


class TerminalSubmissionError(RuntimeError):
    """Raised when the coordination API rejects a terminal run update."""


@dataclass(frozen=True)
class RunController:
    """Claim and execute server-coordinated runs for a single site."""

    site: str
    config: VisitorConfig
    site_config: SiteConfig
    site_adapter: SiteAuthAdapter
    plan_factory: PlanFactory
    lease_client: LeaseClient
    control_client: ControlClient
    browser_factory: BrowserFactory = BrowserManager
    session_factory: SessionFactory = Session
    recorder_factory: RecorderFactory | None = None
    cancellation_min_poll_interval_seconds: float = 2.0
    heartbeat_sleeper: Callable[[float], Any] = asyncio.sleep

    async def run_once(self) -> int:
        """Register, claim at most one run, execute it, and release the lease."""
        registered, payload = await self.lease_client.register()
        if not registered:
            LOG.error("Lease registration failed: %s", payload)
            return int(EXIT_RUNTIME_ERROR)
        heartbeat_handle = self._start_heartbeat()
        try:
            self._raise_if_heartbeat_failed(heartbeat_handle)
            run = await self.lease_client.claim_next(site=self.site)
            self._raise_if_heartbeat_failed(heartbeat_handle)
            if run is None:
                return int(EXIT_OK)
            return await self._execute_with_heartbeat_guard(run, heartbeat_handle)
        except SessionAuthError as exc:
            LOG.error("Authentication setup failed: %s", exc)
            return int(EXIT_AUTH_FAILURE)
        except Exception:
            LOG.exception("Run controller failed")
            return int(EXIT_RUNTIME_ERROR)
        finally:
            await self._stop_heartbeat(heartbeat_handle)
            await self.lease_client.release()

    async def run_forever(self, *, poll_interval_seconds: int = 300) -> int:
        """Run a long-lived worker loop until shutdown or a terminal failure."""
        registered, payload = await self.lease_client.register()
        if not registered:
            LOG.error("Lease registration failed: %s", payload)
            return int(EXIT_RUNTIME_ERROR)
        heartbeat_handle = self._start_heartbeat()
        try:
            while True:
                self._raise_if_heartbeat_failed(heartbeat_handle)
                run = await self.lease_client.claim_next(site=self.site)
                self._raise_if_heartbeat_failed(heartbeat_handle)
                if run is None:
                    await self._sleep_with_heartbeat_guard(max(1, poll_interval_seconds), heartbeat_handle)
                    continue
                code = await self._execute_with_heartbeat_guard(run, heartbeat_handle)
                if code != EXIT_OK:
                    return int(code)
        except (KeyboardInterrupt, asyncio.CancelledError):
            return int(EXIT_OK)
        except Exception:
            LOG.exception("Worker loop failed")
            return int(EXIT_RUNTIME_ERROR)
        finally:
            await self._stop_heartbeat(heartbeat_handle)
            await self.lease_client.release()

    def _start_heartbeat(self) -> asyncio.Future[None]:
        return asyncio.ensure_future(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(max(1, self.config.worker.heartbeat_interval_seconds))
            ok, payload = await self.lease_client.heartbeat_with_recovery(self.heartbeat_sleeper)
            if not ok:
                raise RuntimeError(f"heartbeat failed: {payload.get('reason', 'unknown')}")

    async def _execute_with_heartbeat_guard(self, run: Run, heartbeat_handle: asyncio.Future[None]) -> int:
        execution_handle = asyncio.ensure_future(self._execute(run))
        handles: set[asyncio.Future[Any]] = {execution_handle, heartbeat_handle}
        done, _pending = await asyncio.wait(
            handles,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if heartbeat_handle in done:
            execution_handle.cancel()
            try:
                await execution_handle
            except asyncio.CancelledError:
                pass
            self._raise_if_heartbeat_failed(heartbeat_handle)
            raise RuntimeError("heartbeat stopped")
        return int(await execution_handle)

    async def _sleep_with_heartbeat_guard(self, delay_seconds: int, heartbeat_handle: asyncio.Future[None]) -> None:
        sleep_handle = asyncio.ensure_future(asyncio.sleep(delay_seconds))
        handles: set[asyncio.Future[Any]] = {sleep_handle, heartbeat_handle}
        done, _pending = await asyncio.wait(
            handles,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if heartbeat_handle in done:
            sleep_handle.cancel()
            self._raise_if_heartbeat_failed(heartbeat_handle)
            raise RuntimeError("heartbeat stopped")

    @staticmethod
    def _raise_if_heartbeat_failed(heartbeat_handle: asyncio.Future[None]) -> None:
        if not heartbeat_handle.done():
            return
        if heartbeat_handle.cancelled():
            return
        exc = heartbeat_handle.exception()
        if exc is not None:
            raise exc
        raise RuntimeError("heartbeat stopped")

    async def _execute(self, run: Run) -> int:
        browser = self.browser_factory(self.config, self.site_config, rng=random.Random())
        session = self.session_factory(browser, self.site_adapter, self.config, rng=random.Random())
        recorder: SessionRecorder | None = None
        visit_result: VisitResult | None = None
        outcome = "failed"
        error: str | None = None
        try:
            recorder = self._open_recorder(run, browser)
            if recorder is not None:
                browser.attach_recorder(recorder)

            if not await self._ensure_authenticated(session):
                outcome = "blocked"
                await self._submit_terminal(run.id, outcome=outcome, results={}, error="authentication failed")
                return int(EXIT_AUTH_FAILURE)

            await session.post_login_warmup()
            await browser.start_tracing()
            await browser.enable_har_for_session()
            page = await session.new_page()
            visit_ctx_holder: dict[str, VisitContext] = {}

            def partials() -> dict[str, list[dict[str, Any]]]:
                ctx = visit_ctx_holder.get("ctx")
                return {"extracted": [dict(ctx.extracted)]} if ctx is not None and ctx.extracted else {}

            cancellation = CancellationMonitor(
                client=self.control_client,
                run_id=run.id,
                min_poll_interval_seconds=self.cancellation_min_poll_interval_seconds,
                partials_provider=partials,
            )
            pacing = build_pacing(
                self.config,
                self.site_config,
                browser.rate_limiter,
                rng=random.Random(),
                on_pre_cooldown=lambda boundary: cancellation.check(boundary=boundary),
            )
            visit_ctx = VisitContext(
                page=page,
                pacing=pacing,
                config=self.config,
                site=self.site_config,
                session=session,
                site_adapter=self.site_adapter,
                rng=random.Random(),
                recorder=recorder,
                cancellation=cancellation,
            )
            visit_ctx_holder["ctx"] = visit_ctx
            plan = self.plan_factory(visit_ctx)
            visit_result = await VisitRunner(visit_ctx, propagate_cancellation=True).run(plan)
            outcome = str(visit_result.outcome)
            error = visit_result.error
            await self._submit_terminal(run.id, outcome=outcome, results=visit_result.extracted, error=error)
            return int(EXIT_OK) if outcome == "completed" else int(EXIT_RUNTIME_ERROR)
        except RunCancellationRequested as exc:
            outcome = "cancelled"
            error = str(exc)
            if not await self.lease_client.acknowledge_cancellation(run.id, partials=exc.partials):
                raise TerminalSubmissionError(f"cancellation acknowledgement failed for run {run.id}")
            return int(EXIT_OK)
        except SessionAuthError as exc:
            outcome = "blocked"
            error = str(exc)
            await self._submit_terminal(run.id, outcome=outcome, results={}, error=error)
            return int(EXIT_AUTH_FAILURE)
        except TerminalSubmissionError:
            raise
        except Exception as exc:
            outcome = "failed"
            error = str(exc)
            await self._submit_terminal(run.id, outcome=outcome, results={}, error=error)
            raise
        finally:
            await self._finalize_recording(browser, recorder, visit_result, outcome=outcome, error=error)
            await session.close()

    async def _ensure_authenticated(self, session: Session) -> bool:
        authenticated = await session.start()
        if authenticated:
            return True
        try:
            credentials = _credentials_for_site(self.site) if self.site_adapter.requires_credentials else None
        except KeyError as exc:
            raise SessionAuthError(f"missing credentials for site {self.site}: {exc}") from exc
        return bool(await session.login(cast(Any, credentials)))

    async def _submit_terminal(
        self,
        run_id: str,
        *,
        outcome: str,
        results: dict[str, Any],
        error: str | None,
    ) -> None:
        if not await self.lease_client.submit(run_id, outcome=outcome, results=results, error=error):
            raise TerminalSubmissionError(f"terminal submission failed for run {run_id}")

    def _open_recorder(self, run: Run, browser: BrowserManager) -> SessionRecorder | None:
        factory = self.recorder_factory
        run_ref = RunRef(id=run.id, plan_name=run.plan_name, parameters=run.parameters, site=run.site)
        if factory is not None:
            return factory(
                sessions_dir=site_sessions_dir(self.config, self.site),
                mode=self.config.observability.mode,
                run=run_ref,
                browser_meta_provider=browser.get_browser_metadata,
            )
        return SessionRecorder.open(
            sessions_dir=site_sessions_dir(self.config, self.site),
            mode=self.config.observability.mode,
            run=run_ref,
            browser_meta_provider=browser.get_browser_metadata,
        )

    @staticmethod
    async def _finalize_recording(
        browser: BrowserManager,
        recorder: SessionRecorder | None,
        visit_result: VisitResult | None,
        *,
        outcome: str,
        error: str | None,
    ) -> None:
        if recorder is None:
            return
        await browser.stop_tracing()
        await browser.finalize_har()
        browser.finalize_video()
        if visit_result is not None:
            recorder.update_counters(**visit_result.counters)
        recorder.finalize(outcome=outcome, error=error)

    @staticmethod
    async def _stop_heartbeat(handle: asyncio.Future[None]) -> None:
        if handle.done():
            try:
                handle.exception()
            except asyncio.CancelledError:
                pass
            return
        handle.cancel()
        try:
            await handle
        except asyncio.CancelledError:
            return


def _credentials_for_site(site_name: str) -> Credentials:
    prefix = re.sub(r"[^A-Za-z0-9]+", "_", site_name).upper()
    return Credentials.from_env(prefix)


def site_sessions_dir(visitor: VisitorConfig, site_name: str) -> Path:
    """Return the per-site sessions directory without importing CLI modules."""
    return Path(visitor.observability.sessions_dir).expanduser() / site_name


def build_controller(
    *,
    site_name: str,
    visitor: VisitorConfig,
    site: SiteConfig,
    lease_client: LeaseClient,
    control_client: ControlClient,
) -> RunController:
    """Build the default controller from resolved config and app registration."""
    apps.autoload(site)
    plan_factory = apps.get_app(site.name)
    adapter = SiteAuthAdapter.from_config(site.auth, allowed_host_globs=site.allowed_host_globs)
    return RunController(
        site=site_name,
        config=visitor,
        site_config=site,
        site_adapter=adapter,
        plan_factory=plan_factory,
        lease_client=lease_client,
        control_client=control_client,
    )


__all__ = ["RunController", "build_controller"]
