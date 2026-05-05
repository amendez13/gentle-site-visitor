"""Tests for `gsv config validate`."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from gsv.cli import cli
from gsv.cli._common import redact_config
from tests.cli.conftest import write_config


def test_config_validate_prints_redacted_config(tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
    """Valid config exits 0 and redacts secret-like fields."""
    monkeypatch.setenv("GSV_TEST_API_KEY", "real-token")
    config_path = write_config(tmp_path)

    result = runner.invoke(cli, ["--config", str(config_path), "config", "validate", "--site", "example"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["visitor"]["worker"]["api_key"] == "***"
    assert "real-token" not in result.output
    assert payload["sites"]["example"]["name"] == "example"


def test_config_validate_missing_env_exits_config_code(tmp_path: Path, runner: CliRunner) -> None:
    """Missing required env interpolation exits with the documented config code."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
visitor:
  worker:
    api_key: "${GSV_REQUIRED_TOKEN}"
sites:
  example:
    auth:
      auth_marker_url: "https://example.test/"
""",
        encoding="utf-8",
    )

    result = runner.invoke(cli, ["--config", str(config_path), "config", "validate"])

    assert result.exit_code == 20
    assert "Missing required environment variable" in result.stderr


def test_config_validate_missing_site_exits_config_code(tmp_path: Path, runner: CliRunner) -> None:
    """Selecting an unknown site is a config error."""
    config_path = write_config(tmp_path)

    result = runner.invoke(cli, ["--config", str(config_path), "config", "validate", "--site", "missing"])

    assert result.exit_code == 20
    assert "sites.missing" in result.stderr


def test_redaction_covers_secret_field_markers() -> None:
    """Redaction handles all configured secret-like field names."""
    payload = redact_config(
        {
            "password": "a",
            "api_key": "b",
            "access_token": "c",
            "client_secret": "d",
            "safe": "visible",
        }
    )

    assert payload == {
        "password": "***",
        "api_key": "***",
        "access_token": "***",
        "client_secret": "***",
        "safe": "visible",
    }
