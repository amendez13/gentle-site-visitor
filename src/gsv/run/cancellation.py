"""Cooperative run cancellation primitives."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from gsv.run.control_client import ControlClient

LOG = logging.getLogger(__name__)

PartialResults = dict[str, list[dict[str, Any]]]


class RunCancellationRequested(RuntimeError):
    """Raised when the coordination API asks the worker to stop a run."""

    def __init__(
        self,
        run_id: str,
        *,
        reason: str | None = None,
        partials: PartialResults | None = None,
    ) -> None:
        self.run_id = run_id
        self.reason = reason
        self.partials: PartialResults = partials or {}
        message = f"Run {run_id} cancellation requested"
        if reason:
            message = f"{message}: {reason}"
        super().__init__(message)

    def with_partials(self, partials: PartialResults) -> "RunCancellationRequested":
        """Return a cancellation exception carrying drained partial results."""
        return RunCancellationRequested(self.run_id, reason=self.reason, partials=partials)

    @property
    def partial_results(self) -> PartialResults:
        """Compatibility alias used by callers that prefer the issue wording."""
        return self.partials


class CancellationMonitor:
    """Debounced cancellation poller for visit-runner boundaries."""

    def __init__(
        self,
        *,
        client: ControlClient,
        run_id: str,
        min_poll_interval_seconds: float = 2.0,
        consecutive_cancel_polls: int = 1,
        partials_provider: Callable[[], PartialResults] | None = None,
    ) -> None:
        self.client = client
        self.run_id = run_id
        self.min_poll_interval_seconds = max(0.0, min_poll_interval_seconds)
        self.consecutive_cancel_polls = max(1, consecutive_cancel_polls)
        self._partials_provider = partials_provider
        self._last_poll_at = 0.0
        self._cancel_reason: str | None = None
        self._cancel_observations = 0

    @property
    def cancel_reason(self) -> str | None:
        """Return the last observed cancellation reason."""
        return self._cancel_reason

    async def check(self, *, force: bool = False, boundary: str = "") -> None:
        """Poll for cancellation and raise at a named boundary when confirmed."""
        now = time.monotonic()
        if not force and self._cancel_reason is not None and self._cancel_observations >= self.consecutive_cancel_polls:
            self._raise()
        if not force and now - self._last_poll_at < self.min_poll_interval_seconds:
            return

        self._last_poll_at = now
        LOG.debug("Polling run cancellation", extra={"run_id": self.run_id, "boundary": boundary})
        payload = await self.client.get_run_control(self.run_id)
        if payload is None:
            return

        if bool(payload.get("cancel_requested")):
            self._cancel_observations += 1
            self._cancel_reason = _optional_text(payload.get("cancel_reason")) or "cancel_requested"
            if self._cancel_observations >= self.consecutive_cancel_polls:
                self._raise()
            return

        self._cancel_observations = 0
        self._cancel_reason = None

    def _raise(self) -> None:
        raise RunCancellationRequested(self.run_id, reason=self._cancel_reason, partials=self._partials())

    def _partials(self) -> PartialResults:
        if self._partials_provider is None:
            return {}
        value = self._partials_provider()
        return value if isinstance(value, dict) else {}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


__all__ = ["CancellationMonitor", "PartialResults", "RunCancellationRequested"]
