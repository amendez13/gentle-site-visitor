"""Smoke tests for the public GSV package imports."""

from __future__ import annotations


def test_imports() -> None:
    """Import the package and browser API."""
    import gsv
    import gsv.browser

    assert gsv.__version__ == "0.1.0"
    assert gsv.browser.RateLimiter(max_per_hour=1).remaining == 1
