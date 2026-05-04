"""Site authentication adapter definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from gsv.config.model import SiteAuthConfig

UrlPredicate = Callable[[str], bool]


def _default_challenge_url_predicate(url: str) -> bool:
    lowered = url.lower()
    return "checkpoint" in lowered or "challenge" in lowered


def _default_auth_marker_predicate(auth_marker_url: str) -> UrlPredicate:
    marker = urlparse(auth_marker_url)
    marker_path = marker.path or "/"

    def matches(url: str) -> bool:
        current = urlparse(url)
        path = current.path or "/"
        if current.scheme != marker.scheme or current.netloc != marker.netloc:
            return False
        if marker_path == "/":
            return path == "/"
        return path == marker_path or path.startswith(f"{marker_path.rstrip('/')}/")

    return matches


def _default_auth_marker_wait_glob(auth_marker_url: str) -> str:
    marker = urlparse(auth_marker_url)
    path = marker.path or "/"
    if path == "/":
        return f"{marker.scheme}://{marker.netloc}/**"
    return f"{marker.scheme}://{marker.netloc}{path}**"


def _load_init_script(value: str) -> str:
    path = Path(value).expanduser()
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8")
    return value


@dataclass(frozen=True)
class SiteAuthAdapter:
    """Runtime adapter that supplies site-specific authentication selectors and URLs."""

    auth_marker_url: str
    login_url: str = ""
    cookie_consent_selectors: tuple[str, ...] = ()
    variant_trigger_selectors: tuple[str, ...] = ()
    username_selectors: tuple[str, ...] = ()
    password_selectors: tuple[str, ...] = ()
    submit_selectors: tuple[str, ...] = ()
    warmup_url: str | None = None
    extra_init_scripts: tuple[str, ...] = ()
    allowed_host_globs: tuple[str, ...] = ()
    auth_marker_predicate: UrlPredicate | None = None
    challenge_url_predicate: UrlPredicate = field(default=_default_challenge_url_predicate)
    auth_marker_wait_glob: str | None = None

    def __post_init__(self) -> None:
        if not self.auth_marker_url:
            raise ValueError("auth_marker_url is required")
        credential_groups = (self.username_selectors, self.password_selectors, self.submit_selectors)
        if any(credential_groups) and not all(credential_groups):
            raise ValueError("username_selectors, password_selectors, and submit_selectors must be all provided or all empty")
        if self.auth_marker_predicate is None:
            object.__setattr__(self, "auth_marker_predicate", _default_auth_marker_predicate(self.auth_marker_url))
        if self.auth_marker_wait_glob is None:
            object.__setattr__(self, "auth_marker_wait_glob", _default_auth_marker_wait_glob(self.auth_marker_url))

    @classmethod
    def from_config(
        cls,
        config: SiteAuthConfig,
        *,
        allowed_host_globs: list[str] | tuple[str, ...] = (),
    ) -> "SiteAuthAdapter":
        """Build a runtime adapter from raw site config."""
        return cls(
            auth_marker_url=config.auth_marker_url,
            login_url=config.login_url,
            cookie_consent_selectors=tuple(config.cookie_consent_selectors),
            variant_trigger_selectors=tuple(config.variant_trigger_selectors),
            username_selectors=tuple(config.username_selectors),
            password_selectors=tuple(config.password_selectors),
            submit_selectors=tuple(config.submit_selectors),
            warmup_url=config.warmup_url,
            extra_init_scripts=tuple(_load_init_script(script) for script in config.extra_init_scripts),
            allowed_host_globs=tuple(allowed_host_globs),
        )

    @property
    def requires_credentials(self) -> bool:
        """Return whether this adapter needs a username/password form flow."""
        return bool(self.username_selectors and self.password_selectors and self.submit_selectors)

    @property
    def login_target_url(self) -> str:
        """Return the first URL the login flow should load."""
        return self.login_url or self.auth_marker_url

    def is_authenticated_url(self, url: str) -> bool:
        """Classify whether a URL is an authenticated marker."""
        if self.auth_marker_predicate is None:
            return False
        return self.auth_marker_predicate(url)

    def is_challenge_url(self, url: str) -> bool:
        """Classify whether a URL is a manual verification challenge."""
        return self.challenge_url_predicate(url)
