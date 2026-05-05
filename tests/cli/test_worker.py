"""Tests for `gsv worker` CLI wiring."""

from __future__ import annotations

from dataclasses import replace
from datetime import time
from typing import Any

from click.testing import CliRunner

from gsv.cli import cli
from gsv.cli import server as server_module
from gsv.cli import worker as worker_module
from gsv.config import ScheduleConfig, SiteConfig, VisitorConfig, WorkerConfig
from gsv.schedule import ScheduleProfile
from tests.cli.conftest import write_config


def test_worker_missing_api_key_exits_config_20(tmp_path, runner: CliRunner) -> None:  # type: ignore[no-untyped-def]
    """The coordinated worker refuses to run without an API key."""
    config_path = write_config(tmp_path)

    result = runner.invoke(cli, ["--config", str(config_path), "worker", "--site", "example", "--once"])

    assert result.exit_code == 20
    assert "visitor.worker.api_key is required" in result.stderr


def test_server_dev_help(runner: CliRunner) -> None:
    """The S7 dev server command is registered."""
    result = runner.invoke(cli, ["server", "dev", "--help"])

    assert result.exit_code == 0
    assert "--port" in result.output
    assert "--db" in result.output


def test_worker_runtime_exception_exits_1(runner: CliRunner, monkeypatch) -> None:
    """Unexpected worker errors map to the runtime exit code."""

    async def fail_worker(*args: Any, **kwargs: Any) -> int:
        del args, kwargs
        raise RuntimeError("worker failed")

    monkeypatch.setattr(worker_module, "_run_worker", fail_worker)

    result = runner.invoke(cli, ["worker", "--site", "example", "--once"])

    assert result.exit_code == 1
    assert "Runtime error: worker failed" in result.stderr


async def test_run_worker_builds_controller_and_closes_clients(monkeypatch) -> None:
    """The async worker entrypoint wires lease/control clients into the controller."""
    visitor = replace(VisitorConfig(), worker=WorkerConfig(api_url="http://api.test", api_key="secret"))
    site = SiteConfig(name="example")
    closed: list[str] = []

    class FakeLeaseClient:
        def __init__(self, api_url: str, api_key: str, *, lease_ttl_seconds: int) -> None:
            self.api_url = api_url
            self.api_key = api_key
            self.lease_ttl_seconds = lease_ttl_seconds

        async def aclose(self) -> None:
            closed.append("lease")

    class FakeControlClient:
        def __init__(self, api_url: str, api_key: str) -> None:
            self.api_url = api_url
            self.api_key = api_key

        async def aclose(self) -> None:
            closed.append("control")

    class FakeController:
        async def run_once(self) -> int:
            return 0

        async def run_forever(self, *, poll_interval_seconds: int) -> int:
            del poll_interval_seconds
            return 1

    def build_controller(**kwargs: Any) -> FakeController:
        assert kwargs["site_name"] == "example"
        assert kwargs["visitor"] is visitor
        assert kwargs["site"] is site
        assert kwargs["lease_client"].api_key == "secret"
        assert kwargs["control_client"].api_url == "http://api.test"
        return FakeController()

    monkeypatch.setattr(worker_module, "load_site_config", lambda ctx, site_name: (visitor, site))
    monkeypatch.setattr(worker_module, "LeaseClient", FakeLeaseClient)
    monkeypatch.setattr(worker_module, "ControlClient", FakeControlClient)
    monkeypatch.setattr(worker_module, "build_controller", build_controller)

    once_code = await worker_module._run_worker(  # type: ignore[arg-type]
        object(), site_name="example", once=True, poll_interval=1
    )
    forever_code = await worker_module._run_worker(  # type: ignore[arg-type]
        object(), site_name="example", once=False, poll_interval=2
    )

    assert once_code == 0
    assert forever_code == 1
    assert closed == ["lease", "control", "lease", "control"]


async def test_run_worker_schedule_mode_creates_scheduled_run(monkeypatch) -> None:
    """Scheduled mode creates a run for the slot and executes that exact run id."""
    visitor = replace(
        VisitorConfig(),
        worker=WorkerConfig(api_url="http://api.test", api_key="secret"),
        schedule=ScheduleConfig(
            activity_window_start="08:00",
            activity_window_end="12:00",
            rest_min_minutes=30,
            rest_max_minutes=30,
            profiles=[ScheduleProfile(id="morning", name="Morning", preferred_time="09:00", jitter_minutes=0)],
        ),
    )
    site = SiteConfig(name="example")
    calls: list[Any] = []

    class FakeRun:
        id = "run-morning"

    class FakeLeaseClient:
        def __init__(self, api_url: str, api_key: str, *, lease_ttl_seconds: int) -> None:
            del api_url, api_key, lease_ttl_seconds

        async def create_run(self, **kwargs: Any) -> FakeRun:
            calls.append({"create_run": kwargs})
            return FakeRun()

        async def aclose(self) -> None:
            calls.append("lease_closed")

    class FakeControlClient:
        def __init__(self, api_url: str, api_key: str) -> None:
            del api_url, api_key

        async def aclose(self) -> None:
            calls.append("control_closed")

    class FakeController:
        async def run_once(self, *, run_id: str | None = None) -> int:
            calls.append({"run_once": run_id})
            return 0

    class FakeSchedulingRunner:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def run_today(self, *, target_date: Any) -> int:
            del target_date
            slot = visitor.schedule.profiles[0]
            run_id = await self.kwargs["slot_run_factory"](
                type(
                    "Slot",
                    (),
                    {
                        "profile_id": slot.id,
                        "profile_name": slot.name,
                        "scheduled_time": time(9, 0),
                        "original_time": time(9, 0),
                    },
                )()
            )
            return await self.kwargs["run_controller_factory"]().run_once(run_id=run_id)

    monkeypatch.setattr(worker_module, "load_site_config", lambda ctx, site_name: (visitor, site))
    monkeypatch.setattr(worker_module, "LeaseClient", FakeLeaseClient)
    monkeypatch.setattr(worker_module, "ControlClient", FakeControlClient)
    monkeypatch.setattr(worker_module, "build_controller", lambda **kwargs: FakeController())
    monkeypatch.setattr(worker_module, "SchedulingRunner", FakeSchedulingRunner)

    code = await worker_module._run_worker(  # type: ignore[arg-type]
        object(), site_name="example", once=True, poll_interval=1, scheduled=True
    )

    assert code == 0
    assert calls[0]["create_run"]["profile_id"] == "morning"
    assert calls[1] == {"run_once": "run-morning"}
    assert calls[-2:] == ["lease_closed", "control_closed"]


def test_server_dev_command_sets_default_key_and_runs_uvicorn(runner: CliRunner, monkeypatch) -> None:
    """The dev-server CLI builds the app and starts uvicorn."""
    calls: list[dict[str, Any]] = []

    def fake_create_app(db_path: Any) -> object:
        calls.append({"db_path": db_path})
        return object()

    def fake_run(app: object, **kwargs: Any) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setenv("GSV_API_KEY", "")
    monkeypatch.setattr(server_module, "create_app", fake_create_app)
    monkeypatch.setattr(server_module.uvicorn, "run", fake_run)

    result = runner.invoke(cli, ["server", "dev", "--port", "9999", "--db", "tmp.sqlite"])

    assert result.exit_code == 0
    assert calls[0]["db_path"].name == "tmp.sqlite"
    assert calls[1]["port"] == 9999
