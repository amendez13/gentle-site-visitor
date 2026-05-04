"""Tests for manual challenge handling."""

from __future__ import annotations

import logging

import pytest

from gsv.session import ChallengePolicy


class FlippingPage:
    """Fake page whose URL changes after a few polls."""

    def __init__(self, *, flip_after: int) -> None:
        self.flip_after = flip_after
        self.reads = 0

    @property
    def url(self) -> str:
        self.reads += 1
        if self.reads >= self.flip_after:
            return "https://example.test/home"
        return "https://example.test/challenge"


@pytest.mark.asyncio
async def test_headed_completes_when_url_flips() -> None:
    """Headed mode waits until the page reaches the authenticated marker."""
    policy = ChallengePolicy.headed_wait(timeout_seconds=1, poll_interval_seconds=0)
    page = FlippingPage(flip_after=3)

    handled = await policy.handle(page, lambda url: url.endswith("/home"))

    assert handled is True
    assert page.reads >= 3


@pytest.mark.asyncio
async def test_headed_returns_true_when_already_authenticated() -> None:
    """Challenge handling no-ops if the page is already at the marker."""
    policy = ChallengePolicy.headed_wait(timeout_seconds=1, poll_interval_seconds=0)
    page = FlippingPage(flip_after=1)

    handled = await policy.handle(page, lambda url: url.endswith("/home"))

    assert handled is True


@pytest.mark.asyncio
async def test_headed_times_out(caplog) -> None:  # type: ignore[no-untyped-def]
    """Headed mode returns false if the marker never appears."""
    policy = ChallengePolicy.headed_wait(timeout_seconds=1, poll_interval_seconds=0)
    policy.timeout_seconds = 0
    page = FlippingPage(flip_after=1_000_000)

    with caplog.at_level(logging.WARNING):
        handled = await policy.handle(page, lambda url: url.endswith("/home"))

    assert handled is False
    assert any("did not complete" in record.message for record in caplog.records)


def test_invalid_challenge_mode_rejected() -> None:
    """Only headed and headless policy modes are accepted."""
    with pytest.raises(ValueError, match="mode"):
        ChallengePolicy(mode="manual", timeout_seconds=1)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_headless_returns_false_and_warns_once(caplog) -> None:  # type: ignore[no-untyped-def]
    """Headless mode fails fast instead of waiting for manual work."""
    policy = ChallengePolicy.headless_fail()
    page = FlippingPage(flip_after=100)

    with caplog.at_level(logging.WARNING):
        handled = await policy.handle(page, lambda url: url.endswith("/home"))

    assert handled is False
    warnings = [record for record in caplog.records if "headless mode" in record.message]
    assert len(warnings) == 1
