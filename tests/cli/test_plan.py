"""Tests for S6 plan placeholder."""

from __future__ import annotations

import json

from click.testing import CliRunner

from gsv.cli import cli


def test_plan_show_placeholder_exits_zero(runner: CliRunner) -> None:
    """S6 placeholder exits 0 while making the S8 boundary clear."""
    result = runner.invoke(cli, ["plan", "show", "--site", "example"])

    assert result.exit_code == 0
    assert "S8" in result.stderr


def test_plan_show_placeholder_json(runner: CliRunner) -> None:
    """JSON placeholder is parseable for callers."""
    result = runner.invoke(cli, ["plan", "show", "--site", "example", "--date", "2026-05-05", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["implemented"] is False
    assert payload["slots"] == []
    assert payload["site"] == "example"
