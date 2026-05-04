"""Integration tests for the session auth runner."""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

import pytest

from gsv.browser import BrowserManager
from gsv.config import PacingConfig, SiteConfig, VisitorConfig
from gsv.session import ChallengePolicy, Credentials, Session, SiteAuthAdapter


def build_session(
    fixture_server_url: str,
    tmp_path: Path,
    *,
    adapter: SiteAuthAdapter | None = None,
    challenge_policy: ChallengePolicy | None = None,
) -> Session:
    """Build a session with short deterministic auth delays."""
    visitor = VisitorConfig(
        headless=True,
        pacing=PacingConfig(rate_limit_per_hour=100, post_login_warmup=True),
        manual_verification_timeout_seconds=1,
    )
    site = SiteConfig(
        name="fixture",
        storage_path=str(tmp_path / "state"),
        allowed_host_globs=[f"{fixture_server_url}/**"],
    )
    browser = BrowserManager(visitor, site, rng=random.Random(1))
    auth_adapter = adapter or SiteAuthAdapter(
        auth_marker_url=f"{fixture_server_url}/home",
        login_url=f"{fixture_server_url}/login",
        cookie_consent_selectors=("#missing-cookie", "#accept-cookies"),
        variant_trigger_selectors=("#missing-variant", "#use-another-account"),
        username_selectors=("#missing-username", "#username"),
        password_selectors=("#missing-password", "#password"),
        submit_selectors=("#missing-submit", "#submit"),
        warmup_url=f"{fixture_server_url}/home",
    )
    return Session(
        browser,
        auth_adapter,
        visitor,
        challenge_policy=challenge_policy,
        rng=random.Random(1),
        auth_delay_range=(0, 0),
        form_wait_timeout_ms=100,
        completion_timeout_ms=3000,
    )


async def fast_human_type(page: Any, selector: str, text: str, **_kwargs: Any) -> None:
    """Fast test replacement for per-character typing."""
    await page.fill(selector, text)


@pytest.mark.asyncio
async def test_login_happy_path_uses_selector_fallbacks_and_saves_state(
    fixture_server_url: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The full flow reaches completion and persists browser storage."""
    monkeypatch.setattr("gsv.session.runner.human_type", fast_human_type)
    session = build_session(fixture_server_url, tmp_path)

    try:
        restored = await session.start()
        logged_in = await session.login(Credentials("user@example.test", "correct-password"))

        assert restored is False
        assert logged_in is True
        assert session.is_authenticated is True
        state_file = tmp_path / "state" / "state.json"
        assert state_file.exists()
        assert any(cookie["name"] == "gsv_auth" for cookie in json.loads(state_file.read_text(encoding="utf-8"))["cookies"])
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_start_restores_existing_cookie_state(fixture_server_url: str, tmp_path: Path) -> None:
    """Saved storage state is classified as authenticated without credential entry."""
    storage_dir = tmp_path / "state"
    storage_dir.mkdir()
    (storage_dir / "state.json").write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "gsv_auth",
                        "value": "1",
                        "domain": "127.0.0.1",
                        "path": "/",
                        "expires": -1,
                        "httpOnly": False,
                        "secure": False,
                        "sameSite": "Lax",
                    }
                ],
                "origins": [],
            }
        ),
        encoding="utf-8",
    )
    session = build_session(fixture_server_url, tmp_path)

    try:
        restored = await session.start()

        assert restored is True
        assert session.is_authenticated is True
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_headless_challenge_returns_false(fixture_server_url: str, tmp_path: Path, monkeypatch) -> None:
    """Challenge URLs fail fast under the headless challenge policy."""
    monkeypatch.setattr("gsv.session.runner.human_type", fast_human_type)
    adapter = SiteAuthAdapter(
        auth_marker_url=f"{fixture_server_url}/home",
        login_url=f"{fixture_server_url}/login?challenge=1",
        username_selectors=("#username",),
        password_selectors=("#password",),
        submit_selectors=("#submit",),
    )
    session = build_session(
        fixture_server_url,
        tmp_path,
        adapter=adapter,
        challenge_policy=ChallengePolicy.headless_fail(),
    )

    try:
        logged_in = await session.login(Credentials("user@example.test", "correct-password"))

        assert logged_in is False
        assert session.is_authenticated is False
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_no_auth_adapter_completes_after_marker_load(fixture_server_url: str, tmp_path: Path) -> None:
    """A no-auth adapter reaches completion without credential selectors."""
    adapter = SiteAuthAdapter(auth_marker_url=f"{fixture_server_url}/public-home")
    session = build_session(fixture_server_url, tmp_path, adapter=adapter)

    try:
        logged_in = await session.login()

        assert logged_in is True
        assert session.is_authenticated is True
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_login_failure_emits_diagnostics(
    fixture_server_url: str,
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    """Failed credentials leave the page on login and emit selector diagnostics."""
    monkeypatch.setattr("gsv.session.runner.human_type", fast_human_type)
    session = build_session(fixture_server_url, tmp_path)

    try:
        with caplog.at_level(logging.ERROR):
            logged_in = await session.login(Credentials("user@example.test", "wrong-password"))

        assert logged_in is False
        assert any("reason=still_on_login" in record.getMessage() for record in caplog.records)
        assert any(
            "#missing-username" in record.getMessage() and "#username" in record.getMessage() for record in caplog.records
        )
    finally:
        await session.close()
