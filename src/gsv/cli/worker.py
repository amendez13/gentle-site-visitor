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


@click.command("worker")
@click.option("--site", "site_name", required=True, help="Site name to execute.")
@click.option("--once", is_flag=True, help="Claim at most one run and exit.")
@click.option("--poll-interval", default=300, show_default=True, type=int, help="Seconds between empty claim polls.")
@click.pass_context
def worker_command(ctx: click.Context, site_name: str, once: bool, poll_interval: int) -> None:
    """Run the lease-coordinated worker for one site."""
    try:
        code = asyncio.run(_run_worker(ctx, site_name=site_name, once=once, poll_interval=poll_interval))
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        handle_config_error(exc)
        return
    except Exception as exc:
        click.echo(f"Runtime error: {exc}", err=True)
        raise click.exceptions.Exit(EXIT_RUNTIME_ERROR) from exc
    raise click.exceptions.Exit(code)


async def _run_worker(ctx: click.Context, *, site_name: str, once: bool, poll_interval: int) -> int:
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
        if once:
            return int(await controller.run_once())
        return int(await controller.run_forever(poll_interval_seconds=poll_interval))
    finally:
        await lease_client.aclose()
        await control_client.aclose()


def register(group: click.Group) -> None:
    """Register the worker command."""
    group.add_command(worker_command)


__all__ = ["register", "worker_command"]
