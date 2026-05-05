# mypy: disable-error-code=misc
"""Planning commands for schedule inspection."""

from __future__ import annotations

from datetime import date, datetime, timezone
from random import Random
from typing import Any

import click

from gsv.cli._common import config_path_from_context, echo_json, handle_config_error, load_site_config
from gsv.config import ConfigError
from gsv.config.loader import load_all_configs
from gsv.schedule import PlannedSlot, compute_daily_plan


@click.group("plan")
def plan_group() -> None:
    """Planning commands."""


@click.command("show")
@click.option("--site", default=None, help="Site name to plan for.")
@click.option("--date", "plan_date", default=None, help="YYYY-MM-DD date to inspect.")
@click.option("--seed", default=None, type=int, help="Seed RNG for reproducible output.")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_context
def show_command(ctx: click.Context, site: str | None, plan_date: str | None, seed: int | None, as_json: bool) -> None:
    """Print the computed daily schedule."""
    try:
        site_name = site or ctx.obj.get("site")
        visitor = load_site_config(ctx, site_name)[0] if site_name else load_all_configs(config_path_from_context(ctx))[0]
        selected_date = _parse_date(plan_date)
        slots = compute_daily_plan(
            visitor.schedule.profiles,
            visitor.schedule,
            selected_date,
            rng=Random(seed) if seed is not None else None,
        )
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        handle_config_error(exc)
        return
    if as_json:
        echo_json(
            {
                "date": selected_date.isoformat(),
                "seed": seed,
                "site": site_name,
                "slots": [_slot_payload(slot) for slot in slots],
            }
        )
        return
    _print_table(slots)


def _parse_date(value: str | None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ConfigError("--date must be YYYY-MM-DD") from exc


def _slot_payload(slot: PlannedSlot) -> dict[str, Any]:
    return {
        "profile_id": slot.profile_id,
        "profile_name": slot.profile_name,
        "scheduled_time": slot.scheduled_time.strftime("%H:%M"),
        "original_time": slot.original_time.strftime("%H:%M"),
        "skipped": slot.skipped,
        "skip_reason": slot.skip_reason,
    }


def _print_table(slots: list[PlannedSlot]) -> None:
    rows = [
        [
            str(slot.profile_id),
            slot.profile_name,
            slot.scheduled_time.strftime("%H:%M"),
            slot.original_time.strftime("%H:%M"),
            "skipped" if slot.skipped else "scheduled",
            slot.skip_reason or "",
        ]
        for slot in slots
    ]
    headers = ["PROFILE", "NAME", "SCHEDULED", "ORIGINAL", "STATUS", "SKIP_REASON"]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows)) if rows else len(headers[index])
        for index in range(len(headers))
    ]
    click.echo("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    for row in rows:
        click.echo("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def register(group: click.Group) -> None:
    """Register the plan command group."""
    plan_group.add_command(show_command)
    group.add_command(plan_group)
