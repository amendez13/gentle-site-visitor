"""Evidence sinks used by visit steps before S5 wires session bundles."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol


class EvidenceSink(Protocol):
    """Async sink for app-defined structured visit evidence."""

    async def write(self, event_type: str, payload: Mapping[str, Any]) -> None:
        """Write one evidence event."""


class NullEvidenceSink:
    """Drop evidence events without requiring filesystem state."""

    async def write(self, event_type: str, payload: Mapping[str, Any]) -> None:
        """Accept and drop an evidence event."""
        del event_type, payload


class JsonlEvidenceSink:
    """Append one JSON object per evidence event to a JSONL file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    async def write(self, event_type: str, payload: Mapping[str, Any]) -> None:
        """Append one event to the sink path."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {"event_type": event_type, "payload": dict(payload)}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
