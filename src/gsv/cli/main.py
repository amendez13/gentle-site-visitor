# mypy: disable-error-code=misc
"""Top-level Click command group for the ``gsv`` console script."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from gsv import __version__


@click.group(name="gsv")
@click.version_option(__version__)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("config/config.yaml"),
    show_default=True,
    help="Configuration YAML path.",
)
@click.option("--site", default=None, help="Default site for commands that accept a site.")
@click.option("-v", "--verbose", count=True, help="Increase log verbosity.")
@click.pass_context
def cli(ctx: click.Context, config_path: Path, site: str | None, verbose: int) -> None:
    """Gentle Site Visitor."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    ctx.obj["site"] = site


def register_subcommands(group: click.Group) -> None:
    """Register all subcommands through module-local factories."""
    from gsv.cli import config as config_command
    from gsv.cli import plan, run, server, sessions, worker

    config_command.register(group)
    plan.register(group)
    run.register(group)
    server.register(group)
    sessions.register(group)
    worker.register(group)


register_subcommands(cli)
