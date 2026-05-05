"""Fixtures for CLI tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    """Return an isolated Click runner."""
    return CliRunner()


def write_config(tmp_path: Path, *, sessions_dir: Path | None = None, extra_visitor: str = "") -> Path:
    """Write a minimal valid GSV config for CLI tests."""
    sessions = sessions_dir if sessions_dir is not None else tmp_path / "sessions"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
visitor:
  headless: true
  storage_path: "{tmp_path / "browser"}/{{site}}"
  pacing:
    profile: disabled
    rate_limit_per_hour: 999
    burst_cooldown_interval: 100
  observability:
    mode: always
    trace: false
    har: false
    video: false
    sessions_dir: "{sessions}"
  worker:
    api_key: "${{GSV_TEST_API_KEY:-}}"
{extra_visitor}
sites:
  example:
    app_module: "tests.cli.stub_app"
    storage_path: "{tmp_path / "storage"}"
    auth:
      auth_marker_url: "https://example.test/"
""",
        encoding="utf-8",
    )
    return config_path
