"""Tests for `gsv run`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from gsv.apps import clear_app_registry, register_app
from gsv.browser import RateLimiter
from gsv.cli import cli
from gsv.cli import run as run_module
from gsv.visit import VisitContext, VisitPlan
from tests.cli.conftest import write_config
from tests.cli.stub_app import build_plan


class FakeBrowserManager:
    """BrowserManager test double for the single-shot CLI driver."""

    def __init__(self, visitor_config: Any, site_config: Any, **kwargs: Any) -> None:
        del kwargs
        self.visitor = visitor_config
        self.site = site_config
        self.rate_limiter = RateLimiter(max_per_hour=999)
        self.recorder = None

    def get_browser_metadata(self) -> dict[str, Any]:
        """Return manifest browser metadata."""
        return {
            "chromium_version": "fake",
            "headless": self.visitor.headless,
            "viewport": {"width": 100, "height": 100},
        }

    def attach_recorder(self, recorder: Any) -> None:
        """Capture the active recorder."""
        self.recorder = recorder

    async def start_tracing(self) -> None:
        """No-op trace start."""

    async def stop_tracing(self) -> None:
        """No-op trace stop."""

    async def enable_har_for_session(self) -> None:
        """No-op HAR rotation."""

    async def finalize_har(self) -> None:
        """No-op HAR finalization."""

    def finalize_video(self) -> None:
        """No-op video finalization."""


class FakeSession:
    """Successful session test double."""

    def __init__(self, browser: FakeBrowserManager, adapter: Any, config: Any, **kwargs: Any) -> None:
        del adapter, config, kwargs
        self.browser = browser

    async def start(self) -> bool:
        """Pretend saved auth is already valid."""
        return True

    async def login(self, credentials: Any = None) -> bool:
        """No login needed."""
        del credentials
        return True

    async def post_login_warmup(self) -> bool:
        """No warmup."""
        return False

    async def new_page(self) -> object:
        """Return a fake page object."""
        return object()

    async def close(self) -> None:
        """No-op close."""


class FailingAuthSession(FakeSession):
    """Session test double that fails authentication."""

    async def start(self) -> bool:
        """No saved auth."""
        return False

    async def login(self, credentials: Any = None) -> bool:
        """Login fails."""
        del credentials
        return False


def failing_plan_factory(ctx: VisitContext) -> VisitPlan:
    """Raise a runtime ValueError from app code."""
    del ctx
    raise ValueError("app factory failed")


def test_run_once_writes_session_bundle(tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
    """The S6 driver runs a registered plan and finalizes a manifest."""
    clear_app_registry()
    register_app("example", build_plan)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(run_module, "BrowserManager", FakeBrowserManager)
    monkeypatch.setattr(run_module, "Session", FakeSession)

    result = runner.invoke(cli, ["--config", str(config_path), "run", "example", "--once", "--observability", "always"])

    assert result.exit_code == 0
    session_dirs = list((tmp_path / "sessions" / "example").glob("*_run-cli-*"))
    assert len(session_dirs) == 1
    manifest = json.loads((session_dirs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["outcome"] == "completed"
    assert manifest["run"]["site"] == "example"
    assert manifest["counters"]["stub_steps"] == 1


def test_run_auth_failure_exits_10(tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
    """Login returning false maps to the documented auth code."""
    clear_app_registry()
    register_app("example", build_plan)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(run_module, "BrowserManager", FakeBrowserManager)
    monkeypatch.setattr(run_module, "Session", FailingAuthSession)

    result = runner.invoke(cli, ["--config", str(config_path), "run", "example", "--once"])

    assert result.exit_code == 10
    assert "Auth failed" in result.stderr


def test_run_app_value_error_exits_runtime_not_config(tmp_path: Path, runner: CliRunner, monkeypatch) -> None:
    """App/runtime ValueError maps to code 1, not config code 20."""
    clear_app_registry()
    register_app("example", failing_plan_factory)
    config_path = write_config(tmp_path)
    monkeypatch.setattr(run_module, "BrowserManager", FakeBrowserManager)
    monkeypatch.setattr(run_module, "Session", FakeSession)

    result = runner.invoke(cli, ["--config", str(config_path), "run", "example", "--once"])

    assert result.exit_code == 1
    assert "Runtime error: app factory failed" in result.stderr
