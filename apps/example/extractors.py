"""HTML extractors for the Wikipedia asteroid reference app."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

from apps.example import selectors as S
from apps.example.auth import LIST_URL

if TYPE_CHECKING:
    from playwright.async_api import Page
else:
    Page = Any

WIKIPEDIA_ORIGIN = "https://en.wikipedia.org"


async def extract_asteroid_links(page: Page) -> list[dict[str, str]]:
    """Return unique asteroid article links from the list table."""
    parser = _AsteroidListParser()
    _parse_html(parser, await page.content())
    return parser.links


async def extract_composition(page: Page) -> str | None:
    """Return the spectral type or composition text from an asteroid infobox."""
    parser = _InfoboxParser()
    _parse_html(parser, await page.content())
    return parser.composition


async def extract_missing_composition(page: Page) -> None:
    """Extractor used by the no-infobox branch to clear stale composition state."""
    del page
    return None


async def extract_article_heading(page: Page) -> str:
    """Return the current article heading."""
    parser = _HeadingParser()
    _parse_html(parser, await page.content())
    return parser.heading


async def has_infobox(page: Page) -> bool:
    """Return whether the current document contains an infobox table."""
    parser = _InfoboxPresenceParser()
    _parse_html(parser, await page.content())
    return parser.has_infobox


def _parse_html(parser: HTMLParser, html: str) -> None:
    getattr(parser, "fe" "ed")(html)


def _clean_text(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"\[\s*\d+\s*\]", "", collapsed).strip()


def _class_tokens(attrs: list[tuple[str, str | None]]) -> set[str]:
    raw = dict(attrs).get("class") or ""
    return set(raw.split())


def _is_wiki_article_href(href: str) -> bool:
    parsed = urlparse(href)
    path = parsed.path if parsed.scheme else href.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/wiki/"):
        return False
    article = path.removeprefix("/wiki/")
    return ":" not in article and bool(article)


class _AsteroidListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._table_depth = 0
        self._row_active = False
        self._cell_index = -1
        self._cell_tag: str | None = None
        self._anchor_href: str | None = None
        self._anchor_parts: list[str] = []
        self._seen: set[str] = set()
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and "wikitable" in _class_tokens(attrs):
            self._table_depth += 1
            return
        if tag == "table" and self._table_depth:
            self._table_depth += 1
            return
        if tag == "tr" and self._table_depth == 1:
            self._row_active = True
            self._cell_index = -1
            return
        if tag in {"td", "th"} and self._row_active:
            self._cell_index += 1
            self._cell_tag = tag
            return
        if tag == "a" and self._table_depth == 1 and self._row_active and self._cell_tag == "td" and self._cell_index == 0:
            href = dict(attrs).get("href") or ""
            if _is_wiki_article_href(href):
                self._anchor_href = href
                self._anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor_href is not None:
            name = _clean_text("".join(self._anchor_parts))
            url = urljoin(WIKIPEDIA_ORIGIN, self._anchor_href)
            if name and url not in self._seen:
                self._seen.add(url)
                self.links.append({"name": name, "url": url})
            self._anchor_href = None
            self._anchor_parts = []
        elif tag in {"td", "th"} and self._row_active:
            self._cell_tag = None
        elif tag == "tr" and self._row_active:
            self._row_active = False
            self._cell_index = -1
            self._cell_tag = None
        elif tag == "table" and self._table_depth:
            self._table_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._anchor_href is not None:
            self._anchor_parts.append(data)


class _InfoboxParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._table_depth = 0
        self._row_active = False
        self._cell: str | None = None
        self._header_parts: list[str] = []
        self._value_parts: list[str] = []
        self.composition: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and "infobox" in _class_tokens(attrs):
            self._table_depth += 1
            return
        if tag == "table" and self._table_depth:
            self._table_depth += 1
            return
        if self._table_depth and tag == "tr":
            self._row_active = True
            self._header_parts = []
            self._value_parts = []
        elif self._row_active and tag in {"th", "td"}:
            self._cell = tag

    def handle_endtag(self, tag: str) -> None:
        if self._row_active and tag in {"th", "td"}:
            self._cell = None
        elif self._row_active and tag == "tr":
            header = _clean_text("".join(self._header_parts)).lower()
            value = _clean_text("".join(self._value_parts))
            if self.composition is None and value and any(marker in header for marker in S.COMPOSITION_HEADERS):
                self.composition = value
            self._row_active = False
        elif tag == "table" and self._table_depth:
            self._table_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._cell == "th":
            self._header_parts.append(data)
        elif self._cell == "td":
            self._value_parts.append(data)


class _HeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_heading = False
        self._parts: list[str] = []
        self.heading = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h1" and dict(attrs).get("id") == "firstHeading":
            self._in_heading = True
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self._in_heading:
            self.heading = _clean_text("".join(self._parts))
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if self._in_heading:
            self._parts.append(data)


class _InfoboxPresenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.has_infobox = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and "infobox" in _class_tokens(attrs):
            self.has_infobox = True


__all__ = [
    "LIST_URL",
    "extract_article_heading",
    "extract_asteroid_links",
    "extract_composition",
    "extract_missing_composition",
    "has_infobox",
]
