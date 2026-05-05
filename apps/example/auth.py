"""No-auth adapter for the public Wikipedia example app."""

from __future__ import annotations

from gsv.session import SiteAuthAdapter

LIST_URL = "https://en.wikipedia.org/wiki/List_of_exceptional_asteroids"

WIKIPEDIA_AUTH_ADAPTER = SiteAuthAdapter(
    auth_marker_url=LIST_URL,
    login_url="",
    username_selectors=(),
    password_selectors=(),
    submit_selectors=(),
    warmup_url=LIST_URL,
    allowed_host_globs=("https://en.wikipedia.org/**",),
)

__all__ = ["LIST_URL", "WIKIPEDIA_AUTH_ADAPTER"]
