"""YAML configuration loader for Gentle Site Visitor."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from gsv.config.model import (
    DelayProfileSpec,
    FingerprintConfig,
    IntRange,
    ObservabilityConfig,
    PacingConfig,
    SiteAuthConfig,
    SiteConfig,
    VisitorConfig,
    WorkerConfig,
)


class ConfigError(ValueError):
    """Raised when configuration cannot be parsed safely."""


_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-(.*?))?\}")
_VALID_OBSERVABILITY_MODES = {"off", "failures", "always"}
_VALID_HAR_CONTENT = {"omit", "embed"}


def load_config(config_path: str | Path, site_name: str) -> tuple[VisitorConfig, SiteConfig]:
    """Load visitor defaults and one resolved site configuration."""
    visitor, sites = load_all_configs(config_path)
    try:
        return visitor, sites[site_name]
    except KeyError as exc:
        raise ConfigError(f"sites.{site_name} must be a mapping") from exc


def load_all_configs(config_path: str | Path) -> tuple[VisitorConfig, dict[str, SiteConfig]]:
    """Load visitor defaults and every resolved site configuration."""
    path = Path(config_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ConfigError("Top-level configuration must be a mapping")

    resolved = _resolve_env_in_data(raw)
    visitor_raw = _mapping(resolved.get("visitor", {}), "visitor")
    sites_raw = _mapping(resolved.get("sites", {}), "sites")

    visitor = _parse_visitor(visitor_raw)
    sites: dict[str, SiteConfig] = {}
    for site_name, raw_site in sites_raw.items():
        if not isinstance(site_name, str):
            raise ConfigError("sites keys must be strings")
        site_raw = _mapping(raw_site, f"sites.{site_name}")
        sites[site_name] = _parse_site(site_name, visitor, site_raw)
    return visitor, sites


def _resolve_env_in_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_env_in_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_env_in_data(item) for item in value]
    if isinstance(value, str):
        return _resolve_env_vars(value)
    return value


def _resolve_env_vars(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        default = match.group(2)
        if name in os.environ:
            return os.environ[name]
        if default is not None:
            return default
        raise ConfigError(f"Missing required environment variable: {name}")

    return _ENV_PATTERN.sub(replace, value)


def _parse_visitor(raw: dict[str, Any]) -> VisitorConfig:
    defaults = VisitorConfig()
    return VisitorConfig(
        headless=_as_bool(_with_default(raw.get("headless"), defaults.headless), "visitor.headless"),
        storage_path=_expand_path(_as_str(raw.get("storage_path"), defaults.storage_path)),
        locale=_as_str(raw.get("locale"), defaults.locale),
        timezone_id=_as_str(raw.get("timezone_id"), defaults.timezone_id),
        page_timeout_seconds=max(1, int(raw.get("page_timeout_seconds", defaults.page_timeout_seconds))),
        manual_verification_timeout_seconds=max(
            1,
            int(raw.get("manual_verification_timeout_seconds", defaults.manual_verification_timeout_seconds)),
        ),
        pacing=_parse_pacing(raw.get("pacing")),
        fingerprint=_parse_fingerprint(raw.get("fingerprint")),
        observability=_parse_observability(raw.get("observability")),
        worker=_parse_worker(raw.get("worker")),
    )


def _parse_site(site_name: str, visitor: VisitorConfig, raw: dict[str, Any]) -> SiteConfig:
    storage_path = _expand_path(_as_str(raw.get("storage_path"), visitor.storage_path)).format(site=site_name)
    allowed_host_globs = raw.get("allowed_host_globs", [])
    if allowed_host_globs is None:
        allowed_host_globs = []
    if not isinstance(allowed_host_globs, list) or not all(isinstance(item, str) for item in allowed_host_globs):
        raise ConfigError(f"sites.{site_name}.allowed_host_globs must be a list of strings")
    return SiteConfig(
        name=site_name,
        app_module=_as_str(raw.get("app_module"), ""),
        storage_path=storage_path,
        locale=_as_str(raw.get("locale"), visitor.locale),
        timezone_id=_as_str(raw.get("timezone_id"), visitor.timezone_id),
        page_timeout_seconds=max(1, int(raw.get("page_timeout_seconds", visitor.page_timeout_seconds))),
        allowed_host_globs=list(allowed_host_globs),
        auth=_parse_site_auth(raw.get("auth"), f"sites.{site_name}.auth"),
    )


def _parse_pacing(raw: Any) -> PacingConfig:
    defaults = PacingConfig()
    data = _mapping(raw, "visitor.pacing", allow_none=True)
    profile = _as_str(data.get("profile"), defaults.profile)
    profiles = _parse_delay_profiles(data.get("profiles"), defaults.profiles)
    if profile not in profiles:
        raise ConfigError("visitor.pacing.profile must name a configured profile")
    return PacingConfig(
        profile=profile,
        profiles=profiles,
        rate_limit_per_hour=max(1, int(data.get("rate_limit_per_hour", defaults.rate_limit_per_hour))),
        burst_cooldown_interval=max(1, int(data.get("burst_cooldown_interval", defaults.burst_cooldown_interval))),
        burst_cooldown_range=_parse_float_range(data.get("burst_cooldown_range"), defaults.burst_cooldown_range),
        content_wait_timeout_ms=max(1, int(data.get("content_wait_timeout_ms", defaults.content_wait_timeout_ms))),
        content_wait_reaction_range=_parse_float_range(
            data.get("content_wait_reaction_range"), defaults.content_wait_reaction_range
        ),
        content_wait_with_mouse_move=_as_bool(
            _with_default(data.get("content_wait_with_mouse_move"), defaults.content_wait_with_mouse_move),
            "visitor.pacing.content_wait_with_mouse_move",
        ),
        post_login_warmup=_as_bool(
            _with_default(data.get("post_login_warmup"), defaults.post_login_warmup), "visitor.pacing.post_login_warmup"
        ),
    )


def _parse_site_auth(raw: Any, name: str) -> SiteAuthConfig:
    defaults = SiteAuthConfig()
    data = _mapping(raw, name, allow_none=True)
    return SiteAuthConfig(
        login_url=_as_str(data.get("login_url"), defaults.login_url),
        auth_marker_url=_as_str(data.get("auth_marker_url"), defaults.auth_marker_url),
        cookie_consent_selectors=_parse_str_list(data.get("cookie_consent_selectors"), f"{name}.cookie_consent_selectors"),
        variant_trigger_selectors=_parse_str_list(data.get("variant_trigger_selectors"), f"{name}.variant_trigger_selectors"),
        username_selectors=_parse_str_list(data.get("username_selectors"), f"{name}.username_selectors"),
        password_selectors=_parse_str_list(data.get("password_selectors"), f"{name}.password_selectors"),
        submit_selectors=_parse_str_list(data.get("submit_selectors"), f"{name}.submit_selectors"),
        warmup_url=_as_optional_str(data.get("warmup_url")),
        extra_init_scripts=_parse_str_list(data.get("extra_init_scripts"), f"{name}.extra_init_scripts"),
    )


def _parse_fingerprint(raw: Any) -> FingerprintConfig:
    defaults = FingerprintConfig()
    data = _mapping(raw, "visitor.fingerprint", allow_none=True)
    return FingerprintConfig(
        viewport_width_range=_parse_int_range(data.get("viewport_width_range"), defaults.viewport_width_range),
        viewport_height_range=_parse_int_range(data.get("viewport_height_range"), defaults.viewport_height_range),
    )


def _parse_observability(raw: Any) -> ObservabilityConfig:
    defaults = ObservabilityConfig()
    data = _mapping(raw, "visitor.observability", allow_none=True)
    mode = _as_str(data.get("mode"), defaults.mode)
    if mode not in _VALID_OBSERVABILITY_MODES:
        raise ConfigError("visitor.observability.mode must be one of: off, failures, always")
    har_content = _as_str(data.get("har_content"), defaults.har_content)
    if har_content not in _VALID_HAR_CONTENT:
        raise ConfigError("visitor.observability.har_content must be one of: omit, embed")
    return ObservabilityConfig(
        mode=mode,
        trace=_as_bool(_with_default(data.get("trace"), defaults.trace), "visitor.observability.trace"),
        har=_as_bool(_with_default(data.get("har"), defaults.har), "visitor.observability.har"),
        video=_as_bool(_with_default(data.get("video"), defaults.video), "visitor.observability.video"),
        sessions_dir=_expand_path(_as_str(data.get("sessions_dir"), defaults.sessions_dir)),
        retention_days=max(1, int(data.get("retention_days", defaults.retention_days))),
        max_sessions=max(0, int(data.get("max_sessions", defaults.max_sessions))),
        har_content=har_content,
    )


def _parse_worker(raw: Any) -> WorkerConfig:
    defaults = WorkerConfig()
    data = _mapping(raw, "visitor.worker", allow_none=True)
    return WorkerConfig(
        api_url=_as_str(data.get("api_url"), defaults.api_url),
        api_key=_as_str(data.get("api_key"), defaults.api_key),
        lease_ttl_seconds=max(1, int(data.get("lease_ttl_seconds", defaults.lease_ttl_seconds))),
        heartbeat_interval_seconds=max(1, int(data.get("heartbeat_interval_seconds", defaults.heartbeat_interval_seconds))),
    )


def _parse_int_range(value: Any, default: IntRange) -> IntRange:
    if value is None:
        return default
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ConfigError("Range values must be two-item lists")
    low = int(value[0])
    high = int(value[1])
    if low <= 0 or high <= 0:
        raise ConfigError("Range values must be positive")
    if low > high:
        low, high = high, low
    return (low, high)


def _parse_float_range(value: Any, default: tuple[float, float]) -> tuple[float, float]:
    if value is None:
        return default
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ConfigError("Range values must be two-item lists")
    low = float(value[0])
    high = float(value[1])
    if low < 0 or high < 0:
        raise ConfigError("Range values must be non-negative")
    if low > high:
        low, high = high, low
    return (low, high)


def _parse_delay_profiles(value: Any, defaults: dict[str, DelayProfileSpec]) -> dict[str, DelayProfileSpec]:
    if value is None:
        return dict(defaults)
    if not isinstance(value, dict):
        raise ConfigError("visitor.pacing.profiles must be a mapping")

    registry = dict(defaults)
    for name, raw_spec in value.items():
        if not isinstance(name, str):
            raise ConfigError("visitor.pacing.profiles keys must be strings")
        data = _mapping(raw_spec, f"visitor.pacing.profiles.{name}")
        default = registry.get(name, DelayProfileSpec(min_seconds=0.0, max_seconds=0.0))
        spec = DelayProfileSpec(
            min_seconds=max(0.0, float(data.get("min_seconds", default.min_seconds))),
            max_seconds=max(0.0, float(data.get("max_seconds", default.max_seconds))),
            distraction_chance=min(1.0, max(0.0, float(data.get("distraction_chance", default.distraction_chance)))),
            distraction_min_seconds=max(0.0, float(data.get("distraction_min_seconds", default.distraction_min_seconds))),
            distraction_max_seconds=max(0.0, float(data.get("distraction_max_seconds", default.distraction_max_seconds))),
        )
        if spec.min_seconds > spec.max_seconds:
            spec = DelayProfileSpec(
                min_seconds=spec.max_seconds,
                max_seconds=spec.min_seconds,
                distraction_chance=spec.distraction_chance,
                distraction_min_seconds=spec.distraction_min_seconds,
                distraction_max_seconds=spec.distraction_max_seconds,
            )
        if spec.distraction_min_seconds > spec.distraction_max_seconds:
            spec = DelayProfileSpec(
                min_seconds=spec.min_seconds,
                max_seconds=spec.max_seconds,
                distraction_chance=spec.distraction_chance,
                distraction_min_seconds=spec.distraction_max_seconds,
                distraction_max_seconds=spec.distraction_min_seconds,
            )
        registry[name] = spec
    return registry


def _parse_str_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{name} must be a list of strings")
    return list(value)


def _mapping(value: Any, name: str, *, allow_none: bool = False) -> dict[str, Any]:
    if value is None and allow_none:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    return value


def _expand_path(value: str) -> str:
    if value == "":
        return ""
    return str(Path(value).expanduser())


def _with_default(value: Any, default: Any) -> Any:
    return default if value is None else value


def _as_str(value: Any, default: str) -> str:
    if value is None:
        return default
    return str(value)


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        clean = value.strip().lower()
        if clean in {"1", "true", "yes", "on"}:
            return True
        if clean in {"0", "false", "no", "off", ""}:
            return False
    raise ConfigError(f"{name} must be a boolean")
