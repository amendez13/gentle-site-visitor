"""Session manifest schema for per-run observability bundles."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, cast

ManifestOutcome = Literal["completed", "failed", "cancelled", "blocked", "in_progress"]


@dataclass(frozen=True)
class RunRef:
    """Stable run metadata stored in each session manifest."""

    id: str
    plan_name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    site: str = ""

    @classmethod
    def from_mapping(cls, value: Any) -> "RunRef":
        """Build a run reference from a manifest mapping."""
        data = value if isinstance(value, dict) else {}
        parameters = data.get("parameters")
        return cls(
            id=str(data.get("id", "")),
            plan_name=str(data.get("plan_name", "")),
            parameters=dict(parameters) if isinstance(parameters, dict) else {},
            site=str(data.get("site", "")),
        )


@dataclass(frozen=True)
class BrowserMeta:
    """Browser metadata snapshot captured for a session."""

    chromium_version: str = ""
    user_agent: str = ""
    headless: bool = True
    viewport: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Any) -> "BrowserMeta":
        """Build browser metadata from a manifest or BrowserManager mapping."""
        data = value if isinstance(value, dict) else {}
        viewport = data.get("viewport")
        return cls(
            chromium_version=str(data.get("chromium_version", "")),
            user_agent=str(data.get("user_agent", "")),
            headless=bool(data.get("headless", True)),
            viewport=_int_dict(viewport),
        )


@dataclass(frozen=True)
class SessionManifest:
    """Manifest written to ``manifest.json`` in each session directory."""

    session_id: str
    run: RunRef
    started_at: str
    ended_at: str | None = None
    duration_seconds: float | None = None
    outcome: ManifestOutcome = "in_progress"
    error: str | None = None
    counters: dict[str, int] = field(default_factory=dict)
    browser: BrowserMeta = field(default_factory=BrowserMeta)
    artifacts: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable manifest mapping."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialize the manifest as stable pretty JSON."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, raw: str) -> "SessionManifest":
        """Deserialize a manifest from JSON text."""
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Session manifest must be a JSON object")
        counters = data.get("counters")
        artifacts = data.get("artifacts")
        return cls(
            session_id=str(data.get("session_id", "")),
            run=RunRef.from_mapping(data.get("run")),
            started_at=str(data.get("started_at", "")),
            ended_at=_optional_str(data.get("ended_at")),
            duration_seconds=_optional_float(data.get("duration_seconds")),
            outcome=_manifest_outcome(data.get("outcome")),
            error=_optional_str(data.get("error")),
            counters=_int_dict(counters),
            browser=BrowserMeta.from_mapping(data.get("browser")),
            artifacts=_str_dict(artifacts),
        )


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_dict(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, item in value.items():
        try:
            normalized[str(key)] = int(item)
        except (TypeError, ValueError):
            continue
    return normalized


def _str_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if item is not None}


def _manifest_outcome(value: Any) -> ManifestOutcome:
    if value in {"completed", "failed", "cancelled", "blocked", "in_progress"}:
        return cast(ManifestOutcome, value)
    return "in_progress"
