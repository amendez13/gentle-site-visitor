"""Tests for S7 cancellation polling."""

from __future__ import annotations

import pytest

from gsv.run import CancellationMonitor, RunCancellationRequested


class FakeControlClient:
    """Deterministic control-client double."""

    def __init__(self, payloads: list[dict[str, object] | None]) -> None:
        self.payloads = list(payloads)
        self.calls = 0

    async def get_run_control(self, run_id: str) -> dict[str, object] | None:
        del run_id
        self.calls += 1
        return self.payloads.pop(0) if self.payloads else {"cancel_requested": False, "cancel_reason": None}


async def test_cancellation_monitor_debounces_polling() -> None:
    """Non-forced checks inside the poll interval do not hit the server again."""
    client = FakeControlClient([{"cancel_requested": False, "cancel_reason": None}])
    monitor = CancellationMonitor(client=client, run_id="run-1", min_poll_interval_seconds=60)

    await monitor.check(boundary="first")
    await monitor.check(boundary="second")

    assert client.calls == 1


async def test_cancellation_monitor_force_overrides_debounce() -> None:
    """Forced checks always poll."""
    client = FakeControlClient(
        [
            {"cancel_requested": False, "cancel_reason": None},
            {"cancel_requested": False, "cancel_reason": None},
        ]
    )
    monitor = CancellationMonitor(client=client, run_id="run-1", min_poll_interval_seconds=60)

    await monitor.check(boundary="first")
    await monitor.check(force=True, boundary="second")

    assert client.calls == 2


async def test_cancellation_monitor_raises_with_partials_after_consecutive_cancel_responses() -> None:
    """Cancellation is raised only after the configured confirmation count."""
    client = FakeControlClient(
        [
            {"cancel_requested": True, "cancel_reason": "operator"},
            {"cancel_requested": True, "cancel_reason": "operator"},
        ]
    )
    monitor = CancellationMonitor(
        client=client,
        run_id="run-1",
        min_poll_interval_seconds=0,
        consecutive_cancel_polls=2,
        partials_provider=lambda: {"items": [{"id": "1"}]},
    )

    await monitor.check(boundary="step_pre")
    with pytest.raises(RunCancellationRequested) as exc_info:
        await monitor.check(boundary="step_post")

    assert exc_info.value.run_id == "run-1"
    assert exc_info.value.reason == "operator"
    assert exc_info.value.partial_results == {"items": [{"id": "1"}]}
    assert exc_info.value.with_partials({"items": [{"id": "2"}]}).partial_results == {"items": [{"id": "2"}]}


async def test_cancellation_monitor_does_not_raise_before_required_confirmations_inside_debounce() -> None:
    """A single cancel observation does not raise early when confirmations require another poll."""
    client = FakeControlClient([{"cancel_requested": True, "cancel_reason": "operator"}])
    monitor = CancellationMonitor(
        client=client,
        run_id="run-1",
        min_poll_interval_seconds=60,
        consecutive_cancel_polls=2,
    )

    await monitor.check(boundary="first")
    await monitor.check(boundary="debounced")

    assert client.calls == 1


async def test_cancellation_monitor_handles_missing_payload_and_reasonless_cancel() -> None:
    """Transport misses are swallowed; reasonless cancellation gets a default reason."""
    client = FakeControlClient([None, {"cancel_requested": True, "cancel_reason": None}])
    monitor = CancellationMonitor(client=client, run_id="run-1", min_poll_interval_seconds=0)

    await monitor.check(boundary="first")
    with pytest.raises(RunCancellationRequested) as exc_info:
        await monitor.check(force=True, boundary="second")

    assert exc_info.value.reason == "cancel_requested"
    assert exc_info.value.partial_results == {}
    assert monitor.cancel_reason == "cancel_requested"
