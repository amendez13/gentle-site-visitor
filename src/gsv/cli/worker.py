# mypy: disable-error-code=misc
"""Long-running coordinated worker command."""

from __future__ import annotations

import asyncio

import click

from gsv.cli._common import handle_config_error, load_site_config
from gsv.config import ConfigError
from gsv.run.control_client import ControlClient
from gsv.run.controller import build_controller
from gsv.run.exit_codes import EXIT_RUNTIME_ERROR
from gsv.run.lease_client import LeaseClient
from gsv.schedule import PlannedSlot
from gsv.schedule.runner import SchedulingRunner


@click.command("worker")
@click.option("--site", "site_name", required=True, help="Site name to execute.")
@click.option("--once", is_flag=True, help="Claim at most one run and exit.")
@click.option("--poll-interval", default=300, show_default=True, type=int, help="Seconds between empty claim polls.")
@click.option("--schedule/--poll", "scheduled", default=False, show_default=True, help="Run by schedule instead of polling.")
@click.pass_context
def worker_command(ctx: click.Context, site_name: str, once: bool, poll_interval: int, scheduled: bool) -> None:
    """Run the lease-coordinated worker for one site."""
    try:
        code = asyncio.run(_run_worker(ctx, site_name=site_name, once=once, poll_interval=poll_interval, scheduled=scheduled))
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        handle_config_error(exc)
        return
    except Exception as exc:
        click.echo(f"Runtime error: {exc}", err=True)
        raise click.exceptions.Exit(EXIT_RUNTIME_ERROR) from exc
    raise click.exceptions.Exit(code)


async def _run_worker(ctx: click.Context, *, site_name: str, once: bool, poll_interval: int, scheduled: bool = False) -> int:
    visitor, site = load_site_config(ctx, site_name)
    if not visitor.worker.api_key:
        raise ConfigError("visitor.worker.api_key is required for gsv worker")
    lease_client = LeaseClient(
        visitor.worker.api_url,
        visitor.worker.api_key,
        lease_ttl_seconds=visitor.worker.lease_ttl_seconds,
    )
    control_client = ControlClient(visitor.worker.api_url, visitor.worker.api_key)
    try:
        controller = build_controller(
            site_name=site_name,
            visitor=visitor,
            site=site,
            lease_client=lease_client,
            control_client=control_client,
        )
        if scheduled:
            runner = SchedulingRunner(
                config=visitor,
                run_controller_factory=lambda: controller,
                slot_run_factory=lambda slot: _create_scheduled_run(lease_client, site_name=site_name, slot=slot),
            )
            if once:
                return int(await runner.run_once())
            return int(await runner.run_forever())
        if once:
            return int(await controller.run_once())
        return int(await controller.run_forever(poll_interval_seconds=poll_interval))
    finally:
        await lease_client.aclose()
        await control_client.aclose()


async def _create_scheduled_run(lease_client: LeaseClient, *, site_name: str, slot: PlannedSlot) -> str | None:
    run = await lease_client.create_run(
        site=site_name,
        plan_name=str(slot.profile_id),
        profile_id=slot.profile_id,
        parameters={
            "profile_id": slot.profile_id,
            "profile_name": slot.profile_name,
            "scheduled_time": slot.scheduled_time.strftime("%H:%M"),
            "original_time": slot.original_time.strftime("%H:%M"),
        },
    )
    if run is None:
        raise RuntimeError(f"failed to create scheduled run for profile {slot.profile_id}")
    return str(run.id)


def register(group: click.Group) -> None:
    """Register the worker command."""
    group.add_command(worker_command)


__all__ = ["register", "worker_command"]
