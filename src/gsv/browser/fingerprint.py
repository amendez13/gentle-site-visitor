"""Pure helpers for browser user-agent and viewport fingerprint values."""

from __future__ import annotations

import random
import re
import sys

from gsv.browser.primitives import ViewportSize


def build_user_agent(browser_version: str, platform: str = sys.platform) -> str:
    """Build a Chrome user agent aligned to the installed Chromium version."""
    version_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", browser_version)
    if version_match:
        chrome_version = version_match.group(1)
    else:
        major_match = re.search(r"(\d+)", browser_version)
        major = major_match.group(1) if major_match else "137"
        chrome_version = f"{major}.0.0.0"

    if platform == "darwin":
        platform_token = "Macintosh; Intel Mac OS X 14_6_0"
    elif platform.startswith("linux"):
        platform_token = "X11; Linux x86_64"
    else:
        platform_token = "Windows NT 10.0; Win64; x64"

    return (
        f"Mozilla/5.0 ({platform_token}) " "AppleWebKit/537.36 (KHTML, like Gecko) " f"Chrome/{chrome_version} Safari/537.36"
    )


def build_viewport(
    rng: random.Random,
    width_range: tuple[int, int] = (1260, 1380),
    height_range: tuple[int, int] = (780, 900),
) -> ViewportSize:
    """Build a subtly randomized viewport inside configured ranges."""
    width_min, width_max = _normalize_range(width_range)
    height_min, height_max = _normalize_range(height_range)
    return {
        "width": rng.randint(width_min, width_max),
        "height": rng.randint(height_min, height_max),
    }


def _normalize_range(value: tuple[int, int]) -> tuple[int, int]:
    low, high = value
    if low <= 0 or high <= 0:
        raise ValueError("viewport ranges must be positive")
    if low > high:
        return high, low
    return low, high
