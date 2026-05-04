"""Tests for credential helpers."""

from __future__ import annotations

from gsv.session import Credentials


def test_credentials_from_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Credentials are read from a prefix-scoped environment pair."""
    monkeypatch.setenv("EXAMPLE_USERNAME", "user")
    monkeypatch.setenv("EXAMPLE_PASSWORD", "secret")

    credentials = Credentials.from_env("EXAMPLE")

    assert credentials == Credentials(username="user", password="secret")
