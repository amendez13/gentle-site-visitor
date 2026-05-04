"""Human-cadence browser interaction primitives."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, TypedDict

LOG = logging.getLogger(__name__)

STEALTH_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-component-update",
]

WEBDRIVER_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
});
""".strip()


class ViewportSize(TypedDict):
    """Playwright-compatible viewport payload."""

    width: int
    height: int


def _rng_or_default(rng: random.Random | None) -> random.Random:
    return rng if rng is not None else random.Random()


async def random_delay(min_s: float = 2.0, max_s: float = 5.0, *, rng: random.Random | None = None) -> float:
    """Sleep for a random duration to mimic human behavior."""
    delay = _rng_or_default(rng).uniform(min_s, max_s)
    await asyncio.sleep(delay)
    return delay


async def human_delay(
    min_s: float = 2.0,
    max_s: float = 5.0,
    distraction_chance: float = 0.10,
    distraction_min_s: float = 15.0,
    distraction_max_s: float = 45.0,
    *,
    rng: random.Random | None = None,
) -> float:
    """Sleep using a mostly-short delay profile with occasional long distractions."""
    sampler = _rng_or_default(rng)
    if sampler.random() < distraction_chance:
        delay = sampler.uniform(distraction_min_s, distraction_max_s)
    else:
        delay = sampler.uniform(min_s, max_s)
    await asyncio.sleep(delay)
    return delay


async def random_mouse_move(page: Any, *, rng: random.Random | None = None) -> None:
    """Move the mouse to a random in-viewport position with smooth steps."""
    sampler = _rng_or_default(rng)
    try:
        viewport = getattr(page, "viewport_size", None)
        if not isinstance(viewport, dict):
            try:
                viewport_eval = await page.evaluate("() => ({ width: window.innerWidth, height: window.innerHeight })")
            except Exception:
                viewport_eval = None
            viewport = viewport_eval if isinstance(viewport_eval, dict) else {"width": 1280, "height": 800}

        width = int(viewport.get("width", 1280))
        height = int(viewport.get("height", 800))
        pad_x = min(120, max(20, width // 8))
        pad_y = min(120, max(20, height // 8))

        min_x = min(pad_x, max(1, width - 1))
        max_x = max(min_x, width - pad_x)
        min_y = min(pad_y, max(1, height - 1))
        max_y = max(min_y, height - pad_y)

        target_x = sampler.randint(min_x, max_x)
        target_y = sampler.randint(min_y, max_y)
        await page.mouse.move(target_x, target_y, steps=sampler.randint(5, 15))
        await random_delay(0.1, 0.3, rng=sampler)
    except Exception:
        LOG.debug("Random mouse movement skipped", exc_info=True)


async def click_with_position_jitter(
    page: Any,
    selector: str,
    timeout: int = 3000,
    *,
    rng: random.Random | None = None,
) -> bool:
    """Click a selector with in-element jitter, then fall back to page.click."""
    sampler = _rng_or_default(rng)
    try:
        element = await page.query_selector(selector)
        if element:
            box = await element.bounding_box()
            if isinstance(box, dict) and box.get("width", 0) > 0 and box.get("height", 0) > 0:
                x = box["x"] + box["width"] * sampler.uniform(0.3, 0.7)
                y = box["y"] + box["height"] * sampler.uniform(0.3, 0.7)
                await page.mouse.move(x, y, steps=sampler.randint(4, 12))
                await page.mouse.click(x, y)
                await random_delay(0.05, 0.2, rng=sampler)
                return True
    except Exception:
        LOG.debug("Jitter click failed for selector %s", selector, exc_info=True)

    try:
        await page.click(selector, timeout=timeout)
        return True
    except Exception:
        return False


async def run_humanized_page_dwell(
    page: Any,
    *,
    min_seconds: float = 7.0,
    max_seconds: float = 10.0,
    rng: random.Random | None = None,
) -> float:
    """Simulate human-like read behavior with randomized down/up scroll phases."""
    sampler = _rng_or_default(rng)
    target = sampler.uniform(min_seconds, max_seconds)
    start = time.monotonic()

    down_budget = target * sampler.uniform(0.55, 0.70)
    up_budget = target * sampler.uniform(0.20, 0.35)
    max_motion_budget = target * 0.95
    if down_budget + up_budget > max_motion_budget:
        up_budget = max(target * 0.15, max_motion_budget - down_budget)

    async def scroll_for(duration: float, direction: int) -> None:
        phase_start = time.monotonic()
        while time.monotonic() - phase_start < duration:
            magnitude = sampler.randint(140, 420)
            delta = magnitude if direction > 0 else -sampler.randint(100, 300)
            await random_mouse_move(page, rng=sampler)
            await page.evaluate("dy => window.scrollBy(0, dy)", delta)
            await random_delay(0.25, 0.9, rng=sampler)

    await scroll_for(down_budget, direction=1)
    await scroll_for(up_budget, direction=-1)

    elapsed = time.monotonic() - start
    remaining = target - elapsed
    if remaining > 0:
        await asyncio.sleep(remaining)
    return time.monotonic() - start


async def human_type(page: Any, selector: str, text: str, *, rng: random.Random | None = None) -> None:
    """Type text character-by-character with randomized delays."""
    sampler = _rng_or_default(rng)
    await random_mouse_move(page, rng=sampler)
    clicked = await click_with_position_jitter(page, selector, rng=sampler)
    if not clicked:
        await page.click(selector)
    await page.fill(selector, "")
    for char in text:
        await page.type(selector, char, delay=sampler.randint(50, 150))
    await random_delay(0.3, 0.8, rng=sampler)


async def scroll_page(page: Any, times: int = 3, *, rng: random.Random | None = None) -> None:
    """Scroll down the page to trigger lazy-loaded content."""
    sampler = _rng_or_default(rng)
    for _ in range(times):
        await random_mouse_move(page, rng=sampler)
        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await random_delay(0.5, 1.5, rng=sampler)
