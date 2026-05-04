"""Post-login warmup helper."""

from __future__ import annotations

import random
from typing import Any

from gsv.browser.primitives import random_delay, scroll_page


def _rng_or_default(rng: random.Random | None) -> random.Random:
    return rng if rng is not None else random.Random()


async def post_login_warmup(
    page: Any,
    warmup_url: str | None,
    *,
    initial_delay_range: tuple[float, float] = (3.0, 6.0),
    scroll_count_range: tuple[int, int] = (1, 3),
    closing_delay_range: tuple[float, float] = (2.0, 5.0),
    rng: random.Random | None = None,
) -> bool:
    """Perform a short authenticated read when a site provides a warmup URL."""
    if warmup_url is None:
        return False

    sampler = _rng_or_default(rng)
    await page.goto(warmup_url, wait_until="domcontentloaded")
    await random_delay(*initial_delay_range, rng=sampler)
    scroll_count = sampler.randint(scroll_count_range[0], scroll_count_range[1])
    await scroll_page(page, times=scroll_count, rng=sampler)
    await random_delay(*closing_delay_range, rng=sampler)
    return True
