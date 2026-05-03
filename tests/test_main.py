"""Tests for the main module."""

from tests.module_loader import import_source_module

greet = import_source_module("main").greet


class TestGreet:
    """Tests for the greet function."""

    def test_greet_default(self) -> None:
        """Test greeting with default name."""
        result = greet()
        assert result == "Hello, World!"

    def test_greet_with_name(self) -> None:
        """Test greeting with a specific name."""
        result = greet("Alice")
        assert result == "Hello, Alice!"

    def test_greet_with_none(self) -> None:
        """Test greeting with None explicitly passed."""
        result = greet(None)
        assert result == "Hello, World!"

    def test_greet_with_empty_string(self) -> None:
        """Test greeting with empty string."""
        result = greet("")
        assert result == "Hello, !"


class TestSampleData:
    """Tests demonstrating fixture usage."""

    def test_sample_data_has_key(self, sample_data: dict) -> None:
        """Test that sample_data fixture has expected key."""
        assert "key" in sample_data
        assert sample_data["key"] == "value"

    def test_sample_data_has_number(self, sample_data: dict) -> None:
        """Test that sample_data fixture has expected number."""
        assert sample_data["number"] == 42
