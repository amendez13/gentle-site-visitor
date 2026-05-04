"""Tests for login diagnostics logging."""

from __future__ import annotations

import logging

import pytest

from gsv.session import SiteAuthAdapter
from gsv.session.diagnostics import log_login_diagnostics


class FakeLocator:
    """Fake Playwright locator."""

    def __init__(self, count: int) -> None:
        self._count = count

    async def count(self) -> int:
        return self._count


class FakePage:
    """Fake page with selector counts."""

    url = "https://example.test/login"

    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self.counts.get(selector, 0))

    async def title(self) -> str:
        return "Login"


class BrokenPage(FakePage):
    """Fake page whose diagnostics calls fail."""

    def locator(self, selector: str) -> FakeLocator:
        raise RuntimeError(f"bad selector {selector}")

    async def title(self) -> str:
        raise RuntimeError("title failed")


@pytest.mark.asyncio
async def test_log_login_diagnostics_records_selector_counts(caplog) -> None:  # type: ignore[no-untyped-def]
    """Diagnostics include every selector group in one error record."""
    adapter = SiteAuthAdapter(
        auth_marker_url="https://example.test/home",
        login_url="https://example.test/login",
        cookie_consent_selectors=("#accept",),
        variant_trigger_selectors=("#other",),
        username_selectors=("#username", "input[name='email']"),
        password_selectors=("#password",),
        submit_selectors=("#submit",),
    )
    page = FakePage({"input[name='email']": 1, "#password": 1, "#submit": 1})

    with caplog.at_level(logging.ERROR):
        await log_login_diagnostics(page, adapter, "credential_entry_failed")

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "reason=credential_entry_failed" in message
    assert "username_selectors={'#username': 0, \"input[name='email']\": 1}" in message
    assert "password_selectors={'#password': 1}" in message
    assert "submit_selectors={'#submit': 1}" in message
    assert "cookie_consent_selectors={'#accept': 0}" in message
    assert "variant_trigger_selectors={'#other': 0}" in message


@pytest.mark.asyncio
async def test_log_login_diagnostics_tolerates_page_errors(caplog) -> None:  # type: ignore[no-untyped-def]
    """Diagnostics still emit one record when selector counting or title reads fail."""
    adapter = SiteAuthAdapter(
        auth_marker_url="https://example.test/home",
        username_selectors=("#username",),
    )

    with caplog.at_level(logging.ERROR):
        await log_login_diagnostics(BrokenPage({}), adapter, "failed")

    message = caplog.records[0].getMessage()
    assert "title=" in message
    assert "username_selectors={'#username': 0}" in message
