"""Offline plan tests for the Wikipedia asteroid example app."""

from __future__ import annotations

from apps.example.auth import WIKIPEDIA_AUTH_ADAPTER
from apps.example.selectors import ARTICLE_HEADING, INFOBOX, LIST_ROW_LINK, LIST_TABLE, PAGE_FOOTER
from apps.example.visit import build_plan
from gsv.visit import VisitPlan
from gsv.visit.steps import Branch, Dwell, Extract, ForEach, Navigate, RecordEvent, Scroll, WaitFor


def test_build_plan_returns_expected_top_level_sequence() -> None:
    """The reference app builds a stable, declarative VisitPlan."""
    plan = build_plan()

    assert isinstance(plan, VisitPlan)
    assert [step.name for step in plan.steps] == [
        "navigate_list",
        "wait_for_list",
        "extract_asteroid_links",
        "visit_asteroids",
        "scroll_to_footer",
        "closing_read",
        "record_visit_complete",
        "finalize_example_counters",
    ]
    assert isinstance(plan.steps[0], Navigate)
    assert isinstance(plan.steps[1], WaitFor)
    assert isinstance(plan.steps[2], Extract)
    assert isinstance(plan.steps[3], ForEach)
    assert isinstance(plan.steps[4], Scroll)
    assert isinstance(plan.steps[5], Dwell)
    assert isinstance(plan.steps[6], RecordEvent)


def test_build_plan_limit_sets_for_each_limit() -> None:
    """Manual smoke runs can bound the otherwise full-page scan."""
    plan = build_plan(limit=5)
    step = plan.steps[3]

    assert isinstance(step, ForEach)
    assert step.limit == 5
    assert step.hydration_retry is True


def test_for_each_body_exercises_expected_step_types() -> None:
    """Each asteroid iteration covers navigation, wait, branch, extract, and evidence."""
    plan = build_plan(limit=1)
    step = plan.steps[3]
    assert isinstance(step, ForEach)

    body = step.body_factory({"name": "2 Pallas", "url": "https://en.wikipedia.org/wiki/2_Pallas"})

    assert [item.name for item in body] == [
        "navigate_asteroid",
        "wait_for_article",
        "extract_article_heading",
        "branch_infobox",
        "record_asteroid_extracted",
        "return_to_list",
        "wait_for_list_return",
    ]
    assert any(isinstance(item, Branch) for item in body)
    assert any(isinstance(item, Extract) for item in body)
    assert any(isinstance(item, RecordEvent) for item in body)
    branch = next(item for item in body if isinstance(item, Branch))
    assert any(isinstance(item, WaitFor) and item.selector == INFOBOX for item in branch.then_steps)


def test_selectors_are_non_empty_strings() -> None:
    """Selector constants are centralized and non-empty."""
    for selector in (ARTICLE_HEADING, INFOBOX, LIST_ROW_LINK, LIST_TABLE, PAGE_FOOTER):
        assert isinstance(selector, str)
        assert selector


def test_wikipedia_auth_adapter_is_no_auth() -> None:
    """The reference app exercises the no-credentials adapter path."""
    assert WIKIPEDIA_AUTH_ADAPTER.username_selectors == ()
    assert WIKIPEDIA_AUTH_ADAPTER.password_selectors == ()
    assert WIKIPEDIA_AUTH_ADAPTER.submit_selectors == ()
    assert WIKIPEDIA_AUTH_ADAPTER.requires_credentials is False
