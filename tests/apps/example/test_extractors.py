"""Offline extractor tests for the Wikipedia asteroid example app."""

from __future__ import annotations

from pathlib import Path

from apps.example.extractors import extract_article_heading, extract_asteroid_links, extract_composition, has_infobox

FIXTURES = Path(__file__).parent / "fixtures"


class FakePage:
    """Minimal page double exposing Playwright's async content method."""

    def __init__(self, html: str) -> None:
        self.html = html

    async def content(self) -> str:
        return self.html


def _page(name: str) -> FakePage:
    return FakePage((FIXTURES / name).read_text(encoding="utf-8"))


async def test_extract_asteroid_links_returns_unique_article_links() -> None:
    """The list extractor returns named absolute article URLs."""
    links = await extract_asteroid_links(_page("list_page.html"))

    assert links == [
        {"name": "2 Pallas", "url": "https://en.wikipedia.org/wiki/2_Pallas"},
        {"name": "4 Vesta", "url": "https://en.wikipedia.org/wiki/4_Vesta"},
    ]


async def test_extract_composition_from_infobox() -> None:
    """The composition extractor reads the spectral-type row."""
    composition = await extract_composition(_page("asteroid_page.html"))

    assert composition == "B-type asteroid"


async def test_extract_composition_returns_none_when_missing() -> None:
    """Missing composition rows are represented as None."""
    composition = await extract_composition(_page("no_composition_page.html"))

    assert composition is None


async def test_article_heading_and_infobox_presence() -> None:
    """Small helper extractors use the same fixture parser path."""
    page = _page("asteroid_page.html")

    assert await extract_article_heading(page) == "2 Pallas"
    assert await has_infobox(page) is True
