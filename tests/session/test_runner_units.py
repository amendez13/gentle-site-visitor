"""Focused branch tests for the session runner."""

from __future__ import annotations

from typing import Any

import pytest

from gsv.config import VisitorConfig
from gsv.session import ChallengePolicy, Credentials, Session, SessionAuthError, SiteAuthAdapter


class FakeContext:
    """Fake browser context that records init scripts."""

    def __init__(self) -> None:
        self.init_scripts: list[str] = []

    async def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)


class FakeLocator:
    """Fake locator with a configurable count."""

    def __init__(self, count: int = 1, *, fail: bool = False) -> None:
        self.count = count
        self.fail = fail

    async def count(self) -> int:
        if self.fail:
            raise RuntimeError("selector failed")
        return self.count


class FakePage:
    """Fake page that supports the runner's narrow auth surface."""

    def __init__(
        self,
        *,
        goto_url: str = "https://example.test/login",
        visible_selectors: set[str] | None = None,
        fail_goto: bool = False,
        locator_fail: bool = False,
    ) -> None:
        self.url = "about:blank"
        self.goto_url = goto_url
        self.visible_selectors = visible_selectors or set()
        self.fail_goto = fail_goto
        self.locator_fail = locator_fail

    async def goto(self, _url: str, **_kwargs: Any) -> None:
        if self.fail_goto:
            raise RuntimeError("navigation failed")
        self.url = self.goto_url

    async def wait_for_selector(self, selector: str, **_kwargs: Any) -> None:
        if selector not in self.visible_selectors:
            raise RuntimeError("not visible")

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(1 if selector in self.visible_selectors else 0, fail=self.locator_fail)

    async def title(self) -> str:
        return "Login"


class FakeBrowser:
    """Minimal browser manager for runner branch tests."""

    def __init__(self, page: FakePage) -> None:
        self.context: FakeContext | None = None
        self.page = page
        self.saved = 0
        self.pages_created = 0
        self.closed = False

    async def start(self) -> FakeContext:
        self.context = FakeContext()
        return self.context

    async def new_page(self) -> FakePage:
        self.pages_created += 1
        return self.page

    async def save_session(self) -> None:
        self.saved += 1

    async def close(self) -> None:
        self.closed = True


def make_session(
    page: FakePage,
    adapter: SiteAuthAdapter | None = None,
    *,
    completion_timeout_ms: int = 1,
) -> tuple[Session, FakeBrowser]:
    """Create a runner backed by fake browser primitives."""
    browser = FakeBrowser(page)
    session = Session(
        browser,  # type: ignore[arg-type]
        adapter
        or SiteAuthAdapter(
            auth_marker_url="https://example.test/home",
            login_url="https://example.test/login",
            username_selectors=("#username",),
            password_selectors=("#password",),
            submit_selectors=("#submit",),
        ),
        VisitorConfig(headless=True, manual_verification_timeout_seconds=1),
        auth_delay_range=(0, 0),
        form_wait_timeout_ms=1,
        completion_timeout_ms=completion_timeout_ms,
    )
    return session, browser


@pytest.mark.asyncio
async def test_login_requires_credentials() -> None:
    """Credential adapters reject login attempts without credentials."""
    session, _browser = make_session(FakePage())

    with pytest.raises(SessionAuthError):
        await session.login()


@pytest.mark.asyncio
async def test_login_saves_when_login_url_reaches_auth_marker() -> None:
    """A login URL that redirects to the auth marker short-circuits form entry."""
    session, browser = make_session(FakePage(goto_url="https://example.test/home"))

    logged_in = await session.login(Credentials("u", "p"))

    assert logged_in is True
    assert browser.saved == 1


@pytest.mark.asyncio
async def test_login_handles_challenge_before_form() -> None:
    """Challenge URLs reached before form entry are delegated to the policy."""
    session, browser = make_session(FakePage(goto_url="https://example.test/challenge"))

    logged_in = await session.login(Credentials("u", "p"))

    assert logged_in is False
    assert browser.saved == 0


@pytest.mark.asyncio
async def test_no_auth_challenge_can_complete_and_save() -> None:
    """No-auth adapters still honor challenge policy results."""
    adapter = SiteAuthAdapter(
        auth_marker_url="https://example.test/home",
        auth_marker_predicate=lambda url: url.endswith("/challenge"),
        challenge_url_predicate=lambda url: url.endswith("/challenge"),
    )
    session, browser = make_session(FakePage(goto_url="https://example.test/challenge"), adapter)
    session.challenge_policy = ChallengePolicy.headed_wait(timeout_seconds=1, poll_interval_seconds=0)

    logged_in = await session.login()

    assert logged_in is True
    assert browser.saved == 1


@pytest.mark.asyncio
async def test_no_auth_marker_miss_fails() -> None:
    """No-auth adapters fail if the marker URL does not classify as authenticated."""
    adapter = SiteAuthAdapter(auth_marker_url="https://example.test/home")
    session, browser = make_session(FakePage(goto_url="https://example.test/other"), adapter)

    logged_in = await session.login()

    assert logged_in is False
    assert browser.saved == 0


@pytest.mark.asyncio
async def test_start_returns_false_when_marker_navigation_fails() -> None:
    """Storage restore checks fail closed on navigation errors."""
    session, _browser = make_session(FakePage(fail_goto=True))

    restored = await session.start()

    assert restored is False


@pytest.mark.asyncio
async def test_extra_init_scripts_are_added_before_page_creation() -> None:
    """Adapter init scripts are added to the fresh browser context."""
    adapter = SiteAuthAdapter(auth_marker_url="https://example.test/home", extra_init_scripts=("window.extra = true;",))
    session, browser = make_session(FakePage(goto_url="https://example.test/home"), adapter)

    await session.start()

    assert browser.context is not None
    assert browser.context.init_scripts == ["window.extra = true;"]


@pytest.mark.asyncio
async def test_public_new_page_starts_browser() -> None:
    """Session.new_page proxies to the browser manager."""
    session, browser = make_session(FakePage())

    page = await session.new_page()

    assert page is browser.page
    assert browser.pages_created == 1


@pytest.mark.asyncio
async def test_login_missing_form_emits_failure() -> None:
    """Missing credential selectors fail before typing."""
    session, _browser = make_session(FakePage(visible_selectors=set()))
    session._authenticated = True

    logged_in = await session.login(Credentials("u", "p"))

    assert logged_in is False
    assert session.is_authenticated is False


@pytest.mark.asyncio
async def test_submit_failure_is_reported(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A failed submit selector is classified separately."""
    page = FakePage(visible_selectors={"#username", "#password"})
    session, _browser = make_session(page)

    async def fake_type(_page: Any, _selector: str, _value: str, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr("gsv.session.runner.human_type", fake_type)

    logged_in = await session.login(Credentials("u", "p"))

    assert logged_in is False


@pytest.mark.asyncio
async def test_wait_for_login_completion_respects_timeout_before_still_on_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Login URL failures wait for the configured completion timeout."""
    session, _browser = make_session(FakePage(), completion_timeout_ms=15000)
    page = await session._ensure_page()
    page.url = "https://example.test/login"
    now = 0.0
    reasons: list[str] = []

    def fake_monotonic() -> float:
        return now

    async def fake_sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    async def fake_log_login_diagnostics(_page: Any, _adapter: SiteAuthAdapter, reason: str) -> None:
        reasons.append(reason)

    monkeypatch.setattr("gsv.session.runner.time.monotonic", fake_monotonic)
    monkeypatch.setattr("gsv.session.runner.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("gsv.session.runner.log_login_diagnostics", fake_log_login_diagnostics)

    completed = await session._wait_for_login_completion(page)

    assert completed is False
    assert now >= 15.0
    assert reasons == ["still_on_login"]


@pytest.mark.asyncio
async def test_try_click_tolerates_locator_errors() -> None:
    """Selector count failures are treated as a miss."""
    session, _browser = make_session(FakePage(visible_selectors={"#submit"}, locator_fail=True))

    clicked = await session._try_click(await session._ensure_page(), ("#submit",))

    assert clicked is False


def test_is_login_url_handles_missing_login_url() -> None:
    """The login URL classifier is disabled when adapters omit a login URL."""
    session, _browser = make_session(FakePage(), SiteAuthAdapter(auth_marker_url="https://example.test/home"))

    assert session._is_login_url("https://example.test/login") is False
