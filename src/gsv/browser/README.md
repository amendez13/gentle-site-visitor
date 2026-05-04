# gsv.browser

`gsv.browser` owns the bottom layer of Gentle Site Visitor: Chromium launch
settings, aligned context fingerprint values, persisted Playwright storage
state, per-hour request limiting, and raw human-cadence interaction helpers.

The public API is intentionally small:

- `BrowserManager` creates one Playwright browser/context for a resolved
  `VisitorConfig` and `SiteConfig`.
- `RateLimiter` enforces a sliding-window per-hour cap before new page
  creation.
- `random_delay`, `human_delay`, `random_mouse_move`,
  `click_with_position_jitter`, `human_type`, `scroll_page`, and
  `run_humanized_page_dwell` are low-level primitives that later pacing and
  visit-runner slices compose.
- `build_user_agent` and `build_viewport` keep user-agent construction and
  viewport randomization pure and testable.

All helpers that sample randomness accept an optional `random.Random` so tests
can use seeded behavior. Site-specific values stay outside this package: locale,
timezone, storage path, viewport ranges, rate cap, and HAR host filters all flow
from configuration.

See [ARCHITECTURE.md section 4.1](../../../docs/ARCHITECTURE.md#41-browser--fingerprint-layer-gsvbrowser)
for the browser-layer contract.
