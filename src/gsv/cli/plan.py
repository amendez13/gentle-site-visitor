# mypy: disable-error-code=misc
"""Planning commands reserved for the S8 scheduler implementation."""

from __future__ import annotations

from datetime import date

import click


@click.group("plan")
def plan_group() -> None:
    """Planning commands."""


@click.command("show")
@click.option("--site", default=None, help="Site name to plan for.")
@click.option("--date", "plan_date", default=None, help="YYYY-MM-DD date to inspect.")
@click.option("--seed", default=None, type=int, help="Accepted now; used by S8 scheduling.")
@click.option("--json", "as_json", is_flag=True, help="Emit placeholder JSON.")
@click.pass_context
def show_command(ctx: click.Context, site: str | None, plan_date: str | None, seed: int | None, as_json: bool) -> None:
    """Print the S6 placeholder for schedule planning."""
    site_name = site or ctx.obj.get("site")
    selected_date = plan_date or date.today().isoformat()
    if as_json:
        import json

        click.echo(
            json.dumps(
                {
                    "date": selected_date,
                    "implemented": False,
                    "message": "schedule integration arrives in S8",
                    "seed": seed,
                    "site": site_name,
                    "slots": [],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    click.echo("gsv plan show: schedule integration arrives in S8.", err=True)


def register(group: click.Group) -> None:
    """Register the plan command group."""
    plan_group.add_command(show_command)
    group.add_command(plan_group)
