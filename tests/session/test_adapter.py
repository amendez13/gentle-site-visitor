"""Tests for site auth adapters."""

from __future__ import annotations

import pytest

from gsv.config import SiteAuthConfig
from gsv.session import SiteAuthAdapter


def test_adapter_derives_predicate_and_wait_glob() -> None:
    """The default marker predicate follows the configured marker path."""
    adapter = SiteAuthAdapter(
        auth_marker_url="https://example.test/home",
        login_url="https://example.test/login",
    )

    assert adapter.is_authenticated_url("https://example.test/home?x=1")
    assert adapter.is_authenticated_url("https://example.test/home/settings")
    assert not adapter.is_authenticated_url("https://example.test/login")
    assert not adapter.is_authenticated_url("https://other.example/home")
    assert not adapter.is_authenticated_url("https://example.test/homepage")
    assert adapter.auth_marker_wait_glob == "https://example.test/home**"


def test_adapter_derives_root_wait_glob_and_requires_marker() -> None:
    """Root auth markers get a broad URL glob and missing markers are rejected."""
    adapter = SiteAuthAdapter(auth_marker_url="https://example.test/")

    assert adapter.auth_marker_wait_glob == "https://example.test/**"
    assert adapter.is_authenticated_url("https://example.test/")
    assert not adapter.is_authenticated_url("https://example.test/login")

    try:
        SiteAuthAdapter(auth_marker_url="")
    except ValueError as exc:
        assert "auth_marker_url" in str(exc)
    else:
        raise AssertionError("missing auth marker should fail")


def test_adapter_from_config_loads_selector_tuples_and_inline_scripts() -> None:
    """Raw config lists are converted to immutable runtime tuples."""
    adapter = SiteAuthAdapter.from_config(
        SiteAuthConfig(
            login_url="https://example.test/login",
            auth_marker_url="https://example.test/home",
            cookie_consent_selectors=["#accept"],
            username_selectors=["#username", "input[name='email']"],
            password_selectors=["#password"],
            submit_selectors=["button[type='submit']"],
            warmup_url="https://example.test/home",
            extra_init_scripts=["window.gsv = true;"],
        ),
        allowed_host_globs=["**/*.example.test/**"],
    )

    assert adapter.cookie_consent_selectors == ("#accept",)
    assert adapter.username_selectors == ("#username", "input[name='email']")
    assert adapter.requires_credentials is True
    assert adapter.warmup_url == "https://example.test/home"
    assert adapter.extra_init_scripts == ("window.gsv = true;",)
    assert adapter.allowed_host_globs == ("**/*.example.test/**",)


def test_no_auth_adapter_does_not_require_credentials() -> None:
    """Empty credential selector groups mark a site as no-auth."""
    adapter = SiteAuthAdapter(auth_marker_url="https://example.test/home")

    assert adapter.requires_credentials is False
    assert adapter.login_target_url == "https://example.test/home"


def test_partial_credential_selector_config_is_rejected() -> None:
    """Adapters must be explicit: all credential selector groups or none."""
    with pytest.raises(ValueError, match="username_selectors"):
        SiteAuthAdapter(
            auth_marker_url="https://example.test/home",
            username_selectors=("#username",),
            password_selectors=("#password",),
        )


def test_adapter_reads_extra_init_script_from_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Extra init scripts may be inline JavaScript or file paths."""
    script = tmp_path / "init.js"
    script.write_text("window.loaded = true;", encoding="utf-8")

    adapter = SiteAuthAdapter.from_config(
        SiteAuthConfig(auth_marker_url="https://example.test/home", extra_init_scripts=[str(script)])
    )

    assert adapter.extra_init_scripts == ("window.loaded = true;",)
