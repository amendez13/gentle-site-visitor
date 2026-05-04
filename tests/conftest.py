"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import pytest

from tests.fixtures.server import start_fixture_server


@pytest.fixture
def sample_data() -> dict:
    """Provide sample data for tests.

    Returns:
        A dictionary with sample test data.
    """
    return {
        "key": "value",
        "number": 42,
        "items": ["a", "b", "c"],
    }


@pytest.fixture
def fixture_server_url() -> str:
    """Start the reusable local fixture HTTP server."""
    server = start_fixture_server()
    try:
        yield server.url
    finally:
        server.close()
