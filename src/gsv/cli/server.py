# mypy: disable-error-code=misc
"""Server command group."""

from __future__ import annotations

import os
from pathlib import Path

import click
import uvicorn

from gsv.server.dev import create_app


@click.group("server")
def server_group() -> None:
    """Run reference coordination services."""


@server_group.command("dev")
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address.")
@click.option("--port", default=8085, show_default=True, type=int, help="Bind port.")
@click.option(
    "--db",
    "db_path",
    default=Path("data/dev-server.sqlite"),
    show_default=True,
    type=click.Path(path_type=Path, dir_okay=False),
    help="SQLite database path.",
)
def dev_command(host: str, port: int, db_path: Path) -> None:
    """Start the SQLite-backed reference dev server."""
    if not os.environ.get("GSV_API_KEY"):
        os.environ["GSV_API_KEY"] = "dev"
    app = create_app(db_path)
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        reload=False,
    )


def register(group: click.Group) -> None:
    """Register server commands."""
    group.add_command(server_group)


__all__ = ["register", "server_group"]
