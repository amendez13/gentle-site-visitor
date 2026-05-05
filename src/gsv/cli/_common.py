"""Shared helpers for Click command modules."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, cast

import click

from gsv.config import ConfigError, SiteConfig, VisitorConfig
from gsv.config.loader import load_all_configs, load_config

EXIT_RUNTIME = 1
EXIT_AUTH = 10
EXIT_CONFIG = 20

SECRET_FIELD_MARKERS = ("password", "secret", "token", "api_key")


def config_path_from_context(ctx: click.Context) -> Path:
    """Return the active config path from Click context state."""
    return Path(ctx.obj.get("config_path", "config/config.yaml"))


def load_site_config(
    ctx: click.Context, site_name: str, *, config_path: Path | None = None
) -> tuple[VisitorConfig, SiteConfig]:
    """Load one site configuration using the active global config path."""
    path = config_path if config_path is not None else config_path_from_context(ctx)
    return cast(tuple[VisitorConfig, SiteConfig], load_config(path, site_name))


def site_sessions_dir(visitor: VisitorConfig, site_name: str) -> Path:
    """Return the S6 per-site sessions directory."""
    return Path(visitor.observability.sessions_dir).expanduser() / site_name


def resolve_sessions_dir(
    ctx: click.Context,
    *,
    site: str | None,
    sessions_dir: str | Path | None,
) -> Path:
    """Resolve an explicit or config-derived session directory."""
    if sessions_dir is not None:
        return Path(sessions_dir).expanduser()
    if site:
        visitor, _site_config = load_site_config(ctx, site)
        return site_sessions_dir(visitor, site)
    visitor, _sites = load_all_configs(config_path_from_context(ctx))
    return Path(visitor.observability.sessions_dir).expanduser()


def redact_config(value: Any, *, field_name: str = "") -> Any:
    """Convert dataclass config values to JSON-safe data with secret fields redacted."""
    if any(marker in field_name.lower() for marker in SECRET_FIELD_MARKERS):
        return "***"
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: redact_config(getattr(value, item.name), field_name=item.name) for item in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(key): redact_config(item, field_name=str(key)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_config(item, field_name=field_name) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def echo_json(value: Any) -> None:
    """Print stable JSON for machine-readable command output."""
    click.echo(json.dumps(value, indent=2, sort_keys=True))


def fail_config(message: str) -> None:
    """Emit a config error and exit with the documented config code."""
    click.echo(f"Config error: {message}", err=True)
    raise click.exceptions.Exit(EXIT_CONFIG)


def handle_config_error(exc: Exception) -> None:
    """Normalize config exceptions to the documented CLI exit code."""
    if isinstance(exc, (ConfigError, FileNotFoundError, LookupError, ValueError)):
        fail_config(str(exc))
    raise exc
