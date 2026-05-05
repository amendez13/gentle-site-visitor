# mypy: disable-error-code=misc
"""Configuration inspection commands."""

from __future__ import annotations

from pathlib import Path

import click

from gsv.cli._common import config_path_from_context, echo_json, fail_config, handle_config_error, redact_config
from gsv.config import load_all_configs


@click.group("config")
def config_group() -> None:
    """Configuration commands."""


@click.command("validate")
@click.argument("path", required=False, type=click.Path(path_type=Path, dir_okay=False))
@click.option("--site", default=None, help="Validate and print one site only.")
@click.pass_context
def validate_command(ctx: click.Context, path: Path | None, site: str | None) -> None:
    """Validate config YAML and print redacted resolved values."""
    config_path = path if path is not None else config_path_from_context(ctx)
    site_name = site or ctx.obj.get("site")
    try:
        visitor, sites = load_all_configs(config_path)
    except Exception as exc:
        handle_config_error(exc)
        return

    if site_name is not None and site_name not in sites:
        fail_config(f"sites.{site_name} must be a mapping")

    selected_sites = {site_name: sites[site_name]} if site_name is not None else sites
    if not selected_sites:
        fail_config("sites must define at least one site")

    echo_json(
        {
            "config_path": str(config_path),
            "visitor": redact_config(visitor),
            "sites": {name: redact_config(site_config) for name, site_config in selected_sites.items()},
        }
    )


def register(group: click.Group) -> None:
    """Register the config command group."""
    config_group.add_command(validate_command)
    group.add_command(config_group)
