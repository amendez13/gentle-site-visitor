"""Typed configuration models for Gentle Site Visitor."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

IntRange = tuple[int, int]


@dataclass(frozen=True)
class PacingConfig:
    """Low-level pacing settings consumed by the browser layer."""

    rate_limit_per_hour: int = 90
    post_login_warmup: bool = True


@dataclass(frozen=True)
class FingerprintConfig:
    """Browser fingerprint ranges that should vary by session."""

    viewport_width_range: IntRange = (1260, 1380)
    viewport_height_range: IntRange = (780, 900)


@dataclass(frozen=True)
class ObservabilityConfig:
    """Session artifact toggles read by the browser context builder."""

    mode: str = "failures"
    trace: bool = True
    har: bool = True
    video: bool = False
    sessions_dir: str = "data/sessions"
    har_content: str = "omit"


@dataclass(frozen=True)
class WorkerConfig:
    """Coordination defaults shared with later worker slices."""

    api_url: str = "http://127.0.0.1:8085"
    api_key: str = ""
    lease_ttl_seconds: int = 120
    heartbeat_interval_seconds: int = 30


@dataclass(frozen=True)
class VisitorConfig:
    """Global visitor defaults that can be specialized by each site."""

    headless: bool = True
    storage_path: str = "data/browser/{site}"
    locale: str = "en-US"
    timezone_id: str = "UTC"
    page_timeout_seconds: int = 30
    manual_verification_timeout_seconds: int = 300
    pacing: PacingConfig = field(default_factory=PacingConfig)
    fingerprint: FingerprintConfig = field(default_factory=FingerprintConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    worker: WorkerConfig = field(default_factory=WorkerConfig)


@dataclass(frozen=True)
class SiteAuthConfig:
    """Raw per-site authentication settings from YAML."""

    login_url: str = ""
    auth_marker_url: str = ""
    cookie_consent_selectors: list[str] = field(default_factory=list)
    variant_trigger_selectors: list[str] = field(default_factory=list)
    username_selectors: list[str] = field(default_factory=list)
    password_selectors: list[str] = field(default_factory=list)
    submit_selectors: list[str] = field(default_factory=list)
    warmup_url: str | None = None
    extra_init_scripts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SiteConfig:
    """Resolved per-site browser settings."""

    name: str
    storage_path: str = "data/browser/{site}"
    locale: str = "en-US"
    timezone_id: str = "UTC"
    page_timeout_seconds: int = 30
    allowed_host_globs: list[str] = field(default_factory=list)
    auth: SiteAuthConfig = field(default_factory=SiteAuthConfig)

    @property
    def storage_dir(self) -> Path | None:
        """Return the site storage directory, or None when disabled."""
        if self.storage_path == "":
            return None
        return Path(self.storage_path).expanduser()
