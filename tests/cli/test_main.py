"""Tests for the top-level CLI group."""

from __future__ import annotations

from click.testing import CliRunner

from gsv import __version__
from gsv.cli import cli


def test_cli_version(runner: CliRunner) -> None:
    """`gsv --version` prints the package version."""
    result = runner.invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output


def test_cli_help_lists_registered_commands(runner: CliRunner) -> None:
    """Top-level help exposes S6 commands."""
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "run" in result.output
    assert "sessions" in result.output
    assert "config" in result.output
    assert "plan" in result.output
