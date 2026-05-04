"""Tests for human-cadence browser primitives."""

from __future__ import annotations

import random
from typing import Any

import pytest

from gsv.browser import primitives


class FakeMouse:
    """Capture mouse actions issued by primitives."""

    def __init__(self) -> None:
        self.moves: list[tuple[float, float, int]] = []
        self.clicks: list[tuple[float, float]] = []

    async def move(self, x: float, y: float, *, steps: int) -> None:
        self.moves.append((x, y, steps))

    async def click(self, x: float, y: float) -> None:
        self.clicks.append((x, y))


class FailingMouse(FakeMouse):
    """Mouse double that raises while moving."""

    async def move(self, x: float, y: float, *, steps: int) -> None:
        raise RuntimeError("move failed")


class FakeElement:
    """Fake Playwright element handle with a bounding box."""

    def __init__(self, box: dict[str, float] | None) -> None:
        self.box = box

    async def bounding_box(self) -> dict[str, float] | None:
        return self.box


class FailingElement(FakeElement):
    """Element double whose box lookup fails."""

    async def bounding_box(self) -> dict[str, float] | None:
        raise RuntimeError("box failed")


class FakePage:
    """Small async page double for primitive tests."""

    def __init__(
        self,
        *,
        viewport_size: dict[str, int] | None = None,
        element: FakeElement | None = None,
        click_raises: bool = False,
    ) -> None:
        self.viewport_size = viewport_size
        self.element = element
        self.click_raises = click_raises
        self.mouse = FakeMouse()
        self.clicks: list[tuple[str, int | None]] = []
        self.fills: list[tuple[str, str]] = []
        self.typed: list[tuple[str, str, int]] = []
        self.evaluations: list[tuple[str, Any]] = []

    async def evaluate(self, script: str, arg: Any = None) -> dict[str, int] | None:
        self.evaluations.append((script, arg))
        if "innerWidth" in script:
            return {"width": 320, "height": 240}
        return None

    async def query_selector(self, selector: str) -> FakeElement | None:
        return self.element

    async def click(self, selector: str, *, timeout: int | None = None) -> None:
        if self.click_raises:
            raise RuntimeError("click failed")
        self.clicks.append((selector, timeout))

    async def fill(self, selector: str, value: str) -> None:
        self.fills.append((selector, value))

    async def type(self, selector: str, char: str, *, delay: int) -> None:
        self.typed.append((selector, char, delay))


class EvalRaisesPage(FakePage):
    """Page double whose viewport evaluation fails."""

    async def evaluate(self, script: str, arg: Any = None) -> dict[str, int] | None:
        if "innerWidth" in script:
            raise RuntimeError("eval failed")
        return await super().evaluate(script, arg)


class OneTimeFailClickPage(FakePage):
    """Page double that fails the first click and accepts the second."""

    def __init__(self) -> None:
        super().__init__(element=None)
        self.click_attempts = 0

    async def click(self, selector: str, *, timeout: int | None = None) -> None:
        self.click_attempts += 1
        if self.click_attempts == 1:
            raise RuntimeError("first click failed")
        await super().click(selector, timeout=timeout)


class SequenceRng:
    """Small RNG double for forcing specific dwell branches."""

    def __init__(self, uniform_values: list[float]) -> None:
        self.uniform_values = uniform_values

    def uniform(self, _low: float, _high: float) -> float:
        return self.uniform_values.pop(0)

    def random(self) -> float:
        return 0.0

    def randint(self, low: int, _high: int) -> int:
        return low


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch) -> list[float]:  # type: ignore[no-untyped-def]
    """Replace primitive sleeps with a recorder."""
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(primitives.asyncio, "sleep", fake_sleep)
    return sleeps


@pytest.mark.asyncio
async def test_random_delay_and_human_delay_use_seeded_rng(no_sleep: list[float]) -> None:
    """Delay helpers sample through the injected RNG and return the slept duration."""
    assert await primitives.random_delay(1.0, 1.0, rng=random.Random(1)) == 1.0
    assert await primitives.human_delay(2.0, 2.0, distraction_chance=0.0, rng=random.Random(1)) == 2.0
    assert await primitives.human_delay(distraction_chance=1.0, distraction_min_s=20.0, distraction_max_s=20.0) == 20.0
    assert no_sleep == [1.0, 2.0, 20.0]


@pytest.mark.asyncio
async def test_random_mouse_move_uses_viewport_padding() -> None:
    """Mouse movement stays inside the padded viewport bounds."""
    page = FakePage(viewport_size={"width": 160, "height": 120})

    await primitives.random_mouse_move(page, rng=random.Random(4))

    x, y, steps = page.mouse.moves[0]
    assert 20 <= x <= 140
    assert 20 <= y <= 100
    assert 5 <= steps <= 15


@pytest.mark.asyncio
async def test_random_mouse_move_evaluates_viewport_when_missing() -> None:
    """A page without viewport_size falls back to evaluating window dimensions."""
    page = FakePage(viewport_size=None)

    await primitives.random_mouse_move(page, rng=random.Random(2))

    assert page.evaluations[0][0].startswith("() =>")
    assert page.mouse.moves


@pytest.mark.asyncio
async def test_random_mouse_move_uses_default_viewport_when_evaluation_fails() -> None:
    """Viewport evaluation failures fall back to the default viewport."""
    page = EvalRaisesPage(viewport_size=None)

    await primitives.random_mouse_move(page, rng=random.Random(2))

    assert page.mouse.moves


@pytest.mark.asyncio
async def test_random_mouse_move_suppresses_mouse_errors() -> None:
    """Mouse movement is a best-effort humanization hint."""
    page = FakePage(viewport_size={"width": 160, "height": 120})
    page.mouse = FailingMouse()

    await primitives.random_mouse_move(page, rng=random.Random(2))


@pytest.mark.asyncio
async def test_click_with_position_jitter_uses_bounding_box() -> None:
    """Jittered clicks target the interior of the element box."""
    page = FakePage(element=FakeElement({"x": 10, "y": 20, "width": 100, "height": 50}))

    clicked = await primitives.click_with_position_jitter(page, "#go", rng=random.Random(3))

    assert clicked is True
    assert page.clicks == []
    x, y = page.mouse.clicks[0]
    assert 40 <= x <= 80
    assert 35 <= y <= 55


@pytest.mark.asyncio
async def test_click_with_position_jitter_falls_back_to_page_click() -> None:
    """When jitter cannot be computed, the helper falls back to page.click."""
    page = FakePage(element=None)

    clicked = await primitives.click_with_position_jitter(page, "#fallback", timeout=123, rng=random.Random(1))

    assert clicked is True
    assert page.clicks == [("#fallback", 123)]


@pytest.mark.asyncio
async def test_click_with_position_jitter_falls_back_after_box_error() -> None:
    """Bounding-box failures still allow a plain selector click."""
    page = FakePage(element=FailingElement(None))

    clicked = await primitives.click_with_position_jitter(page, "#fallback", timeout=456, rng=random.Random(1))

    assert clicked is True
    assert page.clicks == [("#fallback", 456)]


@pytest.mark.asyncio
async def test_click_with_position_jitter_returns_false_when_fallback_fails() -> None:
    """A failed selector click reports failure instead of raising."""
    page = FakePage(element=None, click_raises=True)

    assert await primitives.click_with_position_jitter(page, "#missing", rng=random.Random(1)) is False


@pytest.mark.asyncio
async def test_human_type_clears_field_and_types_per_character() -> None:
    """Typing uses a jitter click, clears the field, then sends characters individually."""
    page = FakePage(
        viewport_size={"width": 200, "height": 150}, element=FakeElement({"x": 0, "y": 0, "width": 100, "height": 20})
    )

    await primitives.human_type(page, "#name", "Ada", rng=random.Random(5))

    assert page.fills == [("#name", "")]
    assert [item[1] for item in page.typed] == ["A", "d", "a"]
    assert all(50 <= item[2] <= 150 for item in page.typed)


@pytest.mark.asyncio
async def test_human_type_retries_plain_click_when_jitter_returns_false() -> None:
    """human_type makes a final plain click if the jitter helper reports failure."""
    page = OneTimeFailClickPage()

    await primitives.human_type(page, "#name", "A", rng=random.Random(5))

    assert page.click_attempts == 2
    assert page.fills == [("#name", "")]


@pytest.mark.asyncio
async def test_scroll_page_moves_and_scrolls() -> None:
    """scroll_page combines mouse movement with viewport-height scrolls."""
    page = FakePage(viewport_size={"width": 200, "height": 150})

    await primitives.scroll_page(page, times=2, rng=random.Random(6))

    assert len(page.mouse.moves) == 2
    assert page.evaluations == [
        ("window.scrollBy(0, window.innerHeight)", None),
        ("window.scrollBy(0, window.innerHeight)", None),
    ]


@pytest.mark.asyncio
async def test_run_humanized_page_dwell_scrolls_within_budget(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Dwell splits time into scroll phases and returns elapsed time."""
    page = FakePage(viewport_size={"width": 200, "height": 150})
    current = -0.25

    def fake_monotonic() -> float:
        nonlocal current
        current += 0.25
        return current

    monkeypatch.setattr(primitives.time, "monotonic", fake_monotonic)

    elapsed = await primitives.run_humanized_page_dwell(page, min_seconds=1.0, max_seconds=1.0, rng=random.Random(8))

    assert elapsed > 0
    assert any(call[0] == "dy => window.scrollBy(0, dy)" for call in page.evaluations)


@pytest.mark.asyncio
async def test_run_humanized_page_dwell_sleeps_remaining_budget(
    monkeypatch,  # type: ignore[no-untyped-def]
    no_sleep: list[float],
) -> None:
    """Dwell sleeps the remaining target when scroll phases are short."""
    page = FakePage(viewport_size={"width": 200, "height": 150})
    monkeypatch.setattr(primitives.time, "monotonic", lambda: 0.0)

    elapsed = await primitives.run_humanized_page_dwell(
        page,
        min_seconds=1.0,
        max_seconds=1.0,
        rng=SequenceRng([1.0, 0.0, 0.0]),  # type: ignore[arg-type]
    )

    assert elapsed == 0.0
    assert no_sleep[-1] == 1.0
