"""Browser-management and human-cadence primitives."""

from __future__ import annotations

from gsv.browser.fingerprint import build_user_agent, build_viewport
from gsv.browser.manager import BrowserManager
from gsv.browser.primitives import (
    STEALTH_LAUNCH_ARGS,
    WEBDRIVER_INIT_SCRIPT,
    ViewportSize,
    click_with_position_jitter,
    human_delay,
    human_type,
    random_delay,
    random_mouse_move,
    run_humanized_page_dwell,
    scroll_page,
)
from gsv.browser.rate_limit import RateLimiter

__all__ = [
    "BrowserManager",
    "RateLimiter",
    "STEALTH_LAUNCH_ARGS",
    "ViewportSize",
    "WEBDRIVER_INIT_SCRIPT",
    "build_user_agent",
    "build_viewport",
    "click_with_position_jitter",
    "human_delay",
    "human_type",
    "random_delay",
    "random_mouse_move",
    "run_humanized_page_dwell",
    "scroll_page",
]
