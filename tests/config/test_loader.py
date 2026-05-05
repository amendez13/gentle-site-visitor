"""Tests for the S1 YAML configuration loader."""

from __future__ import annotations

import pytest

from gsv.config import ConfigError, load_all_configs, load_config


def test_load_config_merges_visitor_defaults_and_site_overrides(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Site fields override visitor defaults while nested visitor config remains global."""
    monkeypatch.setenv("GSV_API_KEY", "secret")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
visitor:
  headless: false
  storage_path: "~/gsv/{site}"
  locale: en-GB
  timezone_id: Europe/London
  page_timeout_seconds: 45
  manual_verification_timeout_seconds: 120
  pacing:
    profile: custom
    profiles:
      custom:
        min_seconds: 1.0
        max_seconds: 1.0
      production:
        distraction_chance: 0.2
    rate_limit_per_hour: 12
    burst_cooldown_interval: 4
    burst_cooldown_range: [10.0, 20.0]
    content_wait_timeout_ms: 2500
    content_wait_reaction_range: [0.1, 0.2]
    content_wait_with_mouse_move: false
    post_login_warmup: false
  fingerprint:
    viewport_width_range: [1000, 1100]
    viewport_height_range: [700, 710]
  observability:
    mode: always
    trace: false
    har: true
    video: true
    sessions_dir: "~/gsv-sessions"
    retention_days: 7
    max_sessions: 25
    har_content: embed
  worker:
    api_url: http://127.0.0.1:8085
    api_key: ${GSV_API_KEY}
  schedule:
    activity_window_start: "07:30"
    activity_window_end: "21:00"
    rest_min_minutes: 15
    rest_max_minutes: 45
    profiles:
      - id: morning
        name: Morning
        frequency: weekdays
        preferred_time: "09:15"
        jitter_minutes: 10
      - id: 2
        name: Weekend
        enabled: false
sites:
  example:
    app_module: apps.example
    storage_path: "~/custom-example"
    locale: fr-FR
    rate_limit:
      requests_per_hour: 30
      window_minutes: 15
    allowed_host_globs:
      - "**/*.example.test/**"
    auth:
      login_url: "https://example.test/login"
      auth_marker_url: "https://example.test/home"
      cookie_consent_selectors: ["#accept"]
      variant_trigger_selectors: ["#other"]
      username_selectors: ["#username", "input[name='email']"]
      password_selectors: ["#password"]
      submit_selectors: ["#submit"]
      warmup_url: "https://example.test/home"
      extra_init_scripts: ["window.gsv = true;"]
""",
        encoding="utf-8",
    )

    visitor, site = load_config(config_path, "example")

    assert visitor.headless is False
    assert visitor.pacing.profile == "custom"
    assert visitor.pacing.profiles["custom"].min_seconds == 1.0
    assert visitor.pacing.profiles["production"].distraction_chance == 0.2
    assert visitor.pacing.rate_limit_per_hour == 12
    assert visitor.pacing.burst_cooldown_interval == 4
    assert visitor.pacing.burst_cooldown_range == (10.0, 20.0)
    assert visitor.pacing.content_wait_timeout_ms == 2500
    assert visitor.pacing.content_wait_reaction_range == (0.1, 0.2)
    assert visitor.pacing.content_wait_with_mouse_move is False
    assert visitor.pacing.post_login_warmup is False
    assert visitor.manual_verification_timeout_seconds == 120
    assert visitor.fingerprint.viewport_width_range == (1000, 1100)
    assert visitor.observability.mode == "always"
    assert visitor.observability.trace is False
    assert visitor.observability.video is True
    assert visitor.observability.retention_days == 7
    assert visitor.observability.max_sessions == 25
    assert visitor.observability.har_content == "embed"
    assert visitor.worker.api_key == "secret"
    assert visitor.schedule.activity_window_start == "07:30"
    assert visitor.schedule.activity_window_end == "21:00"
    assert visitor.schedule.rest_min_minutes == 15
    assert visitor.schedule.rest_max_minutes == 45
    assert visitor.schedule.profiles[0].id == "morning"
    assert visitor.schedule.profiles[0].frequency == "weekdays"
    assert visitor.schedule.profiles[1].id == 2
    assert visitor.schedule.profiles[1].enabled is False
    assert site.name == "example"
    assert site.app_module == "apps.example"
    assert site.locale == "fr-FR"
    assert site.timezone_id == "Europe/London"
    assert site.page_timeout_seconds == 45
    assert site.allowed_host_globs == ["**/*.example.test/**"]
    assert site.rate_limit is not None
    assert site.rate_limit.requests_per_hour == 30
    assert site.rate_limit.window_minutes == 15
    assert site.storage_path.endswith("custom-example")
    assert site.auth.login_url == "https://example.test/login"
    assert site.auth.auth_marker_url == "https://example.test/home"
    assert site.auth.username_selectors == ["#username", "input[name='email']"]
    assert site.auth.extra_init_scripts == ["window.gsv = true;"]


def test_load_config_defaults_site_storage_template(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A site can inherit visitor storage_path with the site placeholder resolved."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
visitor:
  storage_path: "data/{site}/state"
sites:
  docs: {}
""",
        encoding="utf-8",
    )

    visitor, site = load_config(config_path, "docs")

    assert visitor.locale == "en-US"
    assert site.storage_path == "data/docs/state"
    assert site.storage_dir is not None
    assert site.rate_limit is None


def test_load_config_rejects_invalid_site_rate_limit(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Per-site rate-limit overrides must be positive mappings."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sites:
  example:
    rate_limit:
      requests_per_hour: 0
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="sites.example.rate_limit.requests_per_hour"):
        load_config(config_path, "example")


def test_load_config_partial_site_rate_limit_inherits_visitor_cap(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Partial site rate-limit overrides keep the visitor request cap."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
visitor:
  pacing:
    rate_limit_per_hour: 12
sites:
  example:
    rate_limit:
      window_minutes: 15
""",
        encoding="utf-8",
    )

    _visitor, site = load_config(config_path, "example")

    assert site.rate_limit is not None
    assert site.rate_limit.requests_per_hour == 12
    assert site.rate_limit.window_minutes == 15


def test_load_config_missing_required_env_raises(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Plain ${VAR} references are required."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
visitor:
  worker:
    api_key: ${MISSING_GSV_KEY}
sites:
  example: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="MISSING_GSV_KEY"):
        load_config(config_path, "example")


def test_load_config_optional_env_default(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """${VAR:-default} references use the fallback when the environment is absent."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
visitor:
  worker:
    api_key: ${OPTIONAL_GSV_KEY:-}
sites:
  example: {}
""",
        encoding="utf-8",
    )

    visitor, _site = load_config(config_path, "example")

    assert visitor.worker.api_key == ""


def test_load_config_rejects_missing_site(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The requested site must exist under sites."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("sites: {}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="sites.example"):
        load_config(config_path, "example")


def test_load_config_ignores_malformed_unrequested_sites(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Single-site loading does not validate unrelated site blocks."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sites:
  example:
    auth:
      auth_marker_url: "https://example.test/"
  unfinished:
    allowed_host_globs: "*.example.test"
""",
        encoding="utf-8",
    )

    _visitor, site = load_config(config_path, "example")

    assert site.name == "example"
    with pytest.raises(ConfigError, match="unfinished.allowed_host_globs"):
        load_all_configs(config_path)


def test_load_config_rejects_bad_allowed_hosts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Allowed host filters must stay as a selector-free list of strings."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
sites:
  example:
    allowed_host_globs: "*.example.test"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="allowed_host_globs"):
        load_config(config_path, "example")


def test_load_config_accepts_null_allowed_hosts_and_disabled_storage(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Optional site host filters and storage can be disabled explicitly."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
visitor:
  storage_path: ""
sites:
  example:
    allowed_host_globs:
""",
        encoding="utf-8",
    )

    _visitor, site = load_config(config_path, "example")

    assert site.allowed_host_globs == []
    assert site.storage_path == ""
    assert site.storage_dir is None


def test_load_config_rejects_missing_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A missing YAML path is reported clearly."""
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.yaml", "example")


def test_load_config_rejects_non_mapping_document(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The top-level YAML document must be a mapping."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("- not-a-mapping\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="Top-level"):
        load_config(config_path, "example")


@pytest.mark.parametrize(
    ("snippet", "message"),
    [
        ("visitor:\n  observability:\n    mode: noisy\nsites:\n  example: {}\n", "mode"),
        ("visitor:\n  observability:\n    har_content: all\nsites:\n  example: {}\n", "har_content"),
        ("visitor:\n  fingerprint:\n    viewport_width_range: [100]\nsites:\n  example: {}\n", "Range values"),
        ("visitor:\n  fingerprint:\n    viewport_width_range: [0, 100]\nsites:\n  example: {}\n", "positive"),
        ("visitor:\n  pacing: bad\nsites:\n  example: {}\n", "visitor.pacing"),
        ("visitor:\n  pacing:\n    profiles: bad\nsites:\n  example: {}\n", "visitor.pacing.profiles"),
        ("visitor:\n  pacing:\n    profile: missing\nsites:\n  example: {}\n", "visitor.pacing.profile"),
        (
            "visitor:\n  pacing:\n    content_wait_reaction_range: [1.0]\nsites:\n  example: {}\n",
            "Range values",
        ),
        ("visitor:\n  headless: flase\nsites:\n  example: {}\n", "visitor.headless"),
        ("visitor:\n  schedule:\n    activity_window_start: '8am'\nsites:\n  example: {}\n", "activity_window_start"),
        (
            "visitor:\n"
            "  schedule:\n"
            "    activity_window_start: '22:00'\n"
            "    activity_window_end: '08:00'\n"
            "sites:\n"
            "  example: {}\n",
            "activity window",
        ),
        ("visitor:\n  schedule:\n    rest_min_minutes: 90\n    rest_max_minutes: 30\nsites:\n  example: {}\n", "rest_min"),
        ("visitor:\n  schedule:\n    profiles: bad\nsites:\n  example: {}\n", "visitor.schedule.profiles"),
        ("visitor:\n  schedule:\n    profiles:\n      - name: missing id\nsites:\n  example: {}\n", "profiles\\[0\\].id"),
        (
            "visitor:\n  schedule:\n    profiles:\n      - id: one\n        frequency: monday\nsites:\n  example: {}\n",
            "profiles\\[0\\].frequency",
        ),
        (
            "sites:\n  example:\n    auth:\n      username_selectors: '#username'\n",
            "sites.example.auth.username_selectors",
        ),
    ],
)
def test_load_config_rejects_invalid_nested_values(
    tmp_path,  # type: ignore[no-untyped-def]
    snippet: str,
    message: str,
) -> None:
    """Nested config sections validate shape and enumerated values."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(snippet, encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        load_config(config_path, "example")


def test_load_config_normalizes_reversed_ranges_and_bool_strings(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Ranges are normalized and common string booleans are parsed."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
visitor:
  headless: "yes"
  fingerprint:
    viewport_width_range: [1100, 1000]
  observability:
    trace: "off"
sites:
  example: {}
""",
        encoding="utf-8",
    )

    visitor, _site = load_config(config_path, "example")

    assert visitor.headless is True
    assert visitor.observability.trace is False
    assert visitor.fingerprint.viewport_width_range == (1000, 1100)


def test_load_config_preserves_empty_api_key_for_null_yaml_value(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A nullable API key uses the empty default instead of the literal string None."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
visitor:
  worker:
    api_key:
sites:
  example: {}
""",
        encoding="utf-8",
    )

    visitor, _site = load_config(config_path, "example")

    assert visitor.worker.api_key == ""
