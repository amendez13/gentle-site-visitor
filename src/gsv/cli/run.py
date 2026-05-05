# mypy: disable-error-code=misc
"""Single-shot in-process visit driver for ``gsv run``."""

from __future__ import annotations

import asyncio
import random
import re
import uuid
from dataclasses import dataclass, replace

import click

from gsv import apps
from gsv.apps import AppRegistryError, PlanFactory
from gsv.browser import BrowserManager
from gsv.cli._common import EXIT_AUTH, EXIT_RUNTIME, handle_config_error, load_site_config, site_sessions_dir
from gsv.config import ConfigError, SiteConfig, VisitorConfig
from gsv.observability import RunRef, SessionRecorder
from gsv.pacing import build_pacing
from gsv.session import Credentials, Session, SessionAuthError, SiteAuthAdapter
from gsv.visit.context import VisitContext, VisitResult
from gsv.visit.runner import VisitRunner


class CliAuthError(RuntimeError):
    """Raised when authentication fails under the documented CLI auth code."""


@dataclass(frozen=True)
class RunSetup:
    """Resolved config and app dependencies for one CLI run."""

    visitor: VisitorConfig
    site: SiteConfig
    plan_factory: PlanFactory
    adapter: SiteAuthAdapter


@click.command("run")
@click.argument("site")
@click.option("--once", is_flag=True, help="Run a single visit immediately.")
@click.option("--headed/--headless", "headed", default=None, help="Override browser headless mode.")
@click.option("--observability", type=click.Choice(["off", "failures", "always"]), default=None)
@click.option("--profile", default=None, help="Override pacing profile.")
@click.pass_context
def run_command(
    ctx: click.Context,
    site: str,
    once: bool,
    headed: bool | None,
    observability: str | None,
    profile: str | None,
) -> None:
    """Run one site visit inline without S7 lease coordination."""
    del once
    try:
        exit_code = asyncio.run(_run_once(ctx, site, headed=headed, observability=observability, profile=profile))
    except CliAuthError as exc:
        click.echo(f"Auth failed: {exc}", err=True)
        raise click.exceptions.Exit(EXIT_AUTH) from exc
    except (AppRegistryError, ConfigError, FileNotFoundError, ValueError) as exc:
        handle_config_error(exc)
        return
    except Exception as exc:
        click.echo(f"Runtime error: {exc}", err=True)
        raise click.exceptions.Exit(EXIT_RUNTIME) from exc
    raise click.exceptions.Exit(exit_code)


async def _run_once(
    ctx: click.Context,
    site_name: str,
    *,
    headed: bool | None,
    observability: str | None,
    profile: str | None,
) -> int:
    setup = _resolve_run_setup(ctx, site_name, headed=headed, observability=observability, profile=profile)
    browser = BrowserManager(setup.visitor, setup.site, rng=random.Random())
    session = Session(browser, setup.adapter, setup.visitor, rng=random.Random())
    recorder: SessionRecorder | None = None
    visit_result: VisitResult | None = None

    try:
        recorder = _open_recorder(setup, browser)
        browser.attach_recorder(recorder)

        await _ensure_authenticated(session, setup.adapter, setup.site.name)
        await session.post_login_warmup()
        await browser.start_tracing()
        await browser.enable_har_for_session()
        page = await session.new_page()
        pacing = build_pacing(setup.visitor, setup.site, browser.rate_limiter, rng=random.Random())
        visit_ctx = VisitContext(
            page=page,
            pacing=pacing,
            config=setup.visitor,
            site=setup.site,
            session=session,
            site_adapter=setup.adapter,
            rng=random.Random(),
            recorder=recorder,
        )
        plan = setup.plan_factory(visit_ctx)
        visit_result = await VisitRunner(visit_ctx).run(plan)
        click.echo(f"Run {visit_result.outcome}: {setup.site.name}")
        if recorder is not None:
            click.echo(f"Session: {recorder.session_dir}")
        return 0 if str(visit_result.outcome) == "completed" else int(EXIT_RUNTIME)
    finally:
        await _finalize_recording(browser, recorder, visit_result)
        await session.close()


def register(group: click.Group) -> None:
    """Register the run command."""
    group.add_command(run_command)


def _credentials_for_site(site_name: str) -> Credentials:
    prefix = re.sub(r"[^A-Za-z0-9]+", "_", site_name).upper()
    return Credentials.from_env(prefix)


def _new_run_id() -> str:
    return f"cli-{uuid.uuid4().hex[:8]}"


def _resolve_run_setup(
    ctx: click.Context,
    site_name: str,
    *,
    headed: bool | None,
    observability: str | None,
    profile: str | None,
) -> RunSetup:
    visitor, site = load_site_config(ctx, site_name)
    if headed is not None:
        visitor = replace(visitor, headless=not headed)
    if observability is not None:
        visitor = replace(visitor, observability=replace(visitor.observability, mode=observability))
    if profile is not None:
        if profile not in visitor.pacing.profiles:
            raise ConfigError(f"visitor.pacing.profile must name a configured profile: {profile}")
        visitor = replace(visitor, pacing=replace(visitor.pacing, profile=profile))

    apps.autoload(site)
    plan_factory = apps.get_app(site.name)
    adapter = SiteAuthAdapter.from_config(site.auth, allowed_host_globs=site.allowed_host_globs)
    return RunSetup(visitor=visitor, site=site, plan_factory=plan_factory, adapter=adapter)


def _open_recorder(setup: RunSetup, browser: BrowserManager) -> SessionRecorder | None:
    return SessionRecorder.open(
        sessions_dir=site_sessions_dir(setup.visitor, setup.site.name),
        mode=setup.visitor.observability.mode,
        run=RunRef(id=_new_run_id(), plan_name=f"{setup.site.name}:cli", parameters={"source": "cli"}, site=setup.site.name),
        browser_meta_provider=browser.get_browser_metadata,
    )


async def _ensure_authenticated(session: Session, adapter: SiteAuthAdapter, site_name: str) -> None:
    authenticated = await session.start()
    if authenticated:
        return
    credentials = _credentials_for_site(site_name) if adapter.requires_credentials else None
    try:
        authenticated = await session.login(credentials)
    except (KeyError, SessionAuthError) as exc:
        raise CliAuthError(str(exc)) from exc
    if not authenticated:
        raise CliAuthError(f"login returned false for site '{site_name}'")


async def _finalize_recording(
    browser: BrowserManager,
    recorder: SessionRecorder | None,
    visit_result: VisitResult | None,
) -> None:
    if recorder is None:
        return
    await browser.stop_tracing()
    await browser.finalize_har()
    browser.finalize_video()
    outcome = visit_result.outcome if visit_result is not None else "failed"
    error = visit_result.error if visit_result is not None else None
    recorder.finalize(outcome=outcome, error=error)
