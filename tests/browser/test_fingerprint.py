"""Tests for browser fingerprint helpers."""

from __future__ import annotations

import random

import pytest

from gsv.browser.fingerprint import build_user_agent, build_viewport


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("darwin", "Macintosh; Intel Mac OS X 14_6_0"),
        ("linux", "X11; Linux x86_64"),
        ("linux2", "X11; Linux x86_64"),
        ("win32", "Windows NT 10.0; Win64; x64"),
    ],
)
def test_build_user_agent_platform_tokens(platform: str, expected: str) -> None:
    """The platform token follows the host family."""
    user_agent = build_user_agent("Chromium 123.4.5.6", platform=platform)

    assert expected in user_agent
    assert "Chrome/123.4.5.6" in user_agent


def test_build_user_agent_falls_back_to_major_or_default() -> None:
    """Partial or empty browser versions still produce a modern UA."""
    assert "Chrome/124.0.0.0" in build_user_agent("HeadlessChrome/124", platform="linux")
    assert "Chrome/137.0.0.0" in build_user_agent("", platform="linux")


def test_build_viewport_uses_seeded_rng_inside_ranges() -> None:
    """Viewport randomization is deterministic when the caller injects RNG."""
    rng = random.Random(7)

    viewport = build_viewport(rng, (100, 110), (200, 210))

    assert 100 <= viewport["width"] <= 110
    assert 200 <= viewport["height"] <= 210
    assert viewport == {"width": 105, "height": 202}


def test_build_viewport_normalizes_and_validates_ranges() -> None:
    """Ranges can be provided high-to-low but must stay positive."""
    viewport = build_viewport(random.Random(1), (110, 100), (210, 200))
    assert 100 <= viewport["width"] <= 110
    assert 200 <= viewport["height"] <= 210

    with pytest.raises(ValueError, match="positive"):
        build_viewport(random.Random(1), (0, 100), (200, 210))
