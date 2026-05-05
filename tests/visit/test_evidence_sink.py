"""Tests for visit evidence sinks."""

from __future__ import annotations

import json

import pytest

from gsv.visit import JsonlEvidenceSink, NullEvidenceSink
from gsv.visit.evidence import NullEvidenceSink as EvidenceModuleNullSink


@pytest.mark.asyncio
async def test_null_evidence_sink_accepts_events() -> None:
    """The default sink drops events without raising."""
    await NullEvidenceSink().write("seen", {"value": 1})
    assert EvidenceModuleNullSink is NullEvidenceSink


@pytest.mark.asyncio
async def test_jsonl_evidence_sink_writes_events(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """JsonlEvidenceSink appends one JSON row per event."""
    path = tmp_path / "evidence.jsonl"
    sink = JsonlEvidenceSink(path)

    await sink.write("seen", {"value": 1})
    await sink.write("done", {"ok": True})

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows == [
        {"event_type": "seen", "payload": {"value": 1}},
        {"event_type": "done", "payload": {"ok": True}},
    ]
