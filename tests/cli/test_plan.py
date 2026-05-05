"""Tests for `gsv plan show`."""

from __future__ import annotations

import json

from click.testing import CliRunner

from gsv.cli import cli
from tests.cli.conftest import write_config


def test_plan_show_prints_deterministic_table(  # type: ignore[no-untyped-def]
    tmp_path,
    runner: CliRunner,
    monkeypatch,
) -> None:
    """Seeded table output is stable across invocations."""
    config_path = write_config(
        tmp_path,
        extra_visitor="""
  schedule:
    activity_window_start: "08:00"
    activity_window_end: "12:00"
    rest_min_minutes: 30
    rest_max_minutes: 30
    profiles:
      - id: morning
        name: Morning
        preferred_time: "09:00"
        jitter_minutes: 5
      - id: midday
        name: Midday
        preferred_time: "09:10"
        jitter_minutes: 0
""",
    )
    monkeypatch.setenv("GSV_TEST_API_KEY", "secret")

    first = runner.invoke(
        cli, ["--config", str(config_path), "plan", "show", "--site", "example", "--date", "2026-05-04", "--seed", "42"]
    )
    second = runner.invoke(
        cli, ["--config", str(config_path), "plan", "show", "--site", "example", "--date", "2026-05-04", "--seed", "42"]
    )

    assert first.exit_code == 0
    assert first.output == second.output
    assert "PROFILE" in first.output
    assert "morning" in first.output
    assert "midday" in first.output


def test_plan_show_json_schema(tmp_path, runner: CliRunner, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """JSON output is stable for automation."""
    config_path = write_config(
        tmp_path,
        extra_visitor="""
  schedule:
    activity_window_start: "08:00"
    activity_window_end: "09:30"
    rest_min_minutes: 30
    rest_max_minutes: 30
    profiles:
      - id: 1
        name: One
        preferred_time: "09:00"
        jitter_minutes: 0
      - id: 2
        name: Two
        preferred_time: "09:05"
        jitter_minutes: 0
      - id: 3
        name: Three
        preferred_time: "09:10"
        jitter_minutes: 0
""",
    )
    monkeypatch.setenv("GSV_TEST_API_KEY", "secret")

    result = runner.invoke(
        cli,
        ["--config", str(config_path), "plan", "show", "--site", "example", "--date", "2026-05-05", "--seed", "42", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["date"] == "2026-05-05"
    assert payload["seed"] == 42
    assert payload["site"] == "example"
    assert payload["slots"][0]["profile_id"] == 1
    assert payload["slots"][-1]["skipped"] is True
    assert payload["slots"][-1]["skip_reason"] == "outside_activity_window"
