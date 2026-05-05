"""Visit plan for the Wikipedia asteroid reference app."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from apps.example import extractors as E
from apps.example import selectors as S
from apps.example.auth import LIST_URL
from gsv.visit import StepResult, VisitContext, VisitPlan
from gsv.visit.steps import Branch, Dwell, Extract, ForEach, Navigate, RecordEvent, Scroll, WaitFor


def build_plan(ctx: VisitContext | None = None, *, limit: int | None = None) -> VisitPlan:
    """Build a visit plan that extracts asteroid composition evidence."""
    del ctx
    resolved_limit = _resolve_limit(limit)
    return VisitPlan(
        steps=[
            Navigate(url=LIST_URL, name="navigate_list", content_marker=S.LIST_TABLE),
            WaitFor(selector=S.LIST_TABLE, name="wait_for_list", retries=1),
            Extract(extractor=E.extract_asteroid_links, output_key="asteroid_links", name="extract_asteroid_links"),
            ForEach(
                items_extractor=E.extract_asteroid_links,
                body_factory=_asteroid_steps,
                name="visit_asteroids",
                limit=resolved_limit,
                hydration_retry=True,
            ),
            Scroll(times=2, name="scroll_to_footer", content_marker=S.PAGE_FOOTER),
            Dwell(
                name="closing_read",
                min_seconds=_env_float("GSV_EXAMPLE_DWELL_MIN", 7.0),
                max_seconds=_env_float("GSV_EXAMPLE_DWELL_MAX", 10.0),
            ),
            RecordEvent("visit_complete", _visit_complete_payload, name="record_visit_complete"),
            FinalizeExampleCounters(),
        ]
    )


def _asteroid_steps(item: Any) -> list[Any]:
    asteroid = _coerce_item(item)
    return [
        Navigate(url=asteroid["url"], name="navigate_asteroid", content_marker=S.ARTICLE_HEADING),
        WaitFor(selector=S.ARTICLE_HEADING, name="wait_for_article", retries=1),
        Extract(extractor=E.extract_article_heading, output_key="article_heading", name="extract_article_heading"),
        Branch(
            condition=_has_infobox,
            then_steps=[
                WaitFor(selector=S.INFOBOX, name="wait_for_infobox", retries=1),
                Extract(extractor=E.extract_composition, output_key="composition", name="extract_composition"),
            ],
            else_steps=[
                Extract(extractor=E.extract_missing_composition, output_key="composition", name="mark_composition_missing"),
            ],
            name="branch_infobox",
        ),
        RecordEvent("asteroid_extracted", _asteroid_payload(asteroid), name="record_asteroid_extracted"),
        Navigate(url=LIST_URL, name="return_to_list", content_marker=S.LIST_TABLE),
        WaitFor(selector=S.LIST_TABLE, name="wait_for_list_return", retries=1),
    ]


async def _has_infobox(ctx: VisitContext) -> bool:
    return bool(await E.has_infobox(ctx.page))


def _asteroid_payload(asteroid: dict[str, str]) -> Any:
    def payload(ctx: VisitContext) -> dict[str, str | None]:
        composition = ctx.extracted.get("composition")
        value = str(composition) if composition not in (None, "") else None
        result = {"name": asteroid["name"], "url": asteroid["url"], "composition": value}
        ctx.extracted.setdefault("asteroid_results", []).append(result)
        return result

    return payload


def _visit_complete_payload(ctx: VisitContext) -> dict[str, int]:
    links = ctx.extracted.get("asteroid_links", [])
    results = ctx.extracted.get("asteroid_results", [])
    extracted = sum(1 for item in results if item.get("composition"))
    return {
        "total": len(links) if isinstance(links, list) else 0,
        "visited": len(results) if isinstance(results, list) else 0,
        "extracted": extracted,
        "missing": max(0, len(results) - extracted) if isinstance(results, list) else 0,
    }


def _resolve_limit(limit: int | None) -> int | None:
    if limit is not None:
        return limit
    raw = os.getenv("GSV_EXAMPLE_LIMIT")
    if raw in (None, ""):
        return None
    value = int(raw)
    return value if value > 0 else None


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw in (None, "") else float(raw)


def _coerce_item(item: Any) -> dict[str, str]:
    if isinstance(item, dict):
        return {"name": str(item["name"]), "url": str(item["url"])}
    raise TypeError("asteroid items must be dictionaries with name and url")


@dataclass
class FinalizeExampleCounters:
    """Populate the reference-app counters promised by the S9 smoke contract."""

    name: str = "finalize_example_counters"
    content_marker: str | None = None

    async def execute(self, ctx: VisitContext) -> StepResult:
        ctx.counters["actions_total"] = ctx.counters.get("requests_made", 0)
        ctx.counters.setdefault("cooldowns", 0)
        ctx.counters.setdefault("hydration_retries", 0)
        ctx.counters.setdefault("cancellation_boundary", 0)
        return StepResult(name=self.name, outcome="ok")


__all__ = ["build_plan"]
