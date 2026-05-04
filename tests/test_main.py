"""Tests for the main module."""

from tests.module_loader import import_source_module

main_module = import_source_module("main")
greet = main_module.greet


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


def test_main_configures_logging_and_prints_greeting(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """Test the executable entry point."""
    configured = False

    def fake_configure_logging() -> None:
        nonlocal configured
        configured = True

    monkeypatch.setattr(main_module, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(
        main_module,
        "get_release_info",
        lambda: {
            "tag": "v1.2.3",
            "commit": "abc123456789",
            "short_commit": "abc1234",
            "source": "test",
        },
    )

    main_module.main()

    assert configured is True
    assert capsys.readouterr().out == "Hello, World!\n"
