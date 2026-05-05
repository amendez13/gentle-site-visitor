"""Content-aware post-navigation waits for docs/ARCHITECTURE.md section 4.3."""

from __future__ import annotations

import random
from typing import Any

from gsv.browser.primitives import random_delay, random_mouse_move


class ContentAwareWait:
    """Wait for optional content markers before applying a reaction delay."""

    def __init__(
        self,
        *,
        timeout_ms: int,
        reaction_range: tuple[float, float],
        with_mouse_move: bool,
        rng: random.Random | None = None,
    ) -> None:
        if timeout_ms < 1:
            raise ValueError("timeout_ms must be at least 1")
        if reaction_range[0] < 0 or reaction_range[1] < 0:
            raise ValueError("reaction_range values must be non-negative")
        self._timeout_ms = timeout_ms
        self._reaction_range = (min(reaction_range), max(reaction_range))
        self._with_mouse_move = with_mouse_move
        self._rng = rng if rng is not None else random.Random()

    async def maybe_run(self, page: Any, content_marker: str | None) -> None:
        """Run the post-content wait sequence when a marker is configured."""
        if content_marker is None:
            return
        await page.wait_for_selector(content_marker, timeout=self._timeout_ms)
        await random_delay(*self._reaction_range, rng=self._rng)
        if self._with_mouse_move:
            await random_mouse_move(page, rng=self._rng)
