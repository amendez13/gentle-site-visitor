# S10 — Hardening

> **Slice:** S10 of 10. See [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md).
> **Architecture refs:** [ARCHITECTURE.md §3](../ARCHITECTURE.md#3-layered-architecture), [ARCHITECTURE.md §4.7](../ARCHITECTURE.md#47-observability-layer-gsvobservability).
> **Status:** Not started. **Depends on S9.**

---

## 1. Goal

Pull in the proven-but-optional features from CareerExplorer that didn't make the v0 critical path, plus close the gaps surfaced by [S9 § 6 Discoveries](S09-reference-app.md#6-discoveries-feeds-s10). Each S10 item is opt-in and off by default — turning S10 on must never change behavior for an app that didn't ask for it.

S10 is the slice where we earn the right to call v0 "complete" by paying off the IOUs from earlier slices: per-site rate-limit overrides nobody needed yet, hydration-retry counters that are emitted but not surfaced, pagination caps that LinkedIn needed but `apps/example/` didn't, and an integrity-audit-style probe that mirrors LinkedIn's panel-probe without naming any LinkedIn behavior.

After this slice:

1. An app can override `requests_per_hour` per site in YAML and the override propagates into `RateLimiter` at construction time.
2. `manifest.json` exposes the framework-level counters (`hydration_retries`, `cooldowns`, `cancellation_boundary`, ...) under a stable schema.
3. `Pagination`-style caps (max-pages-per-list, max-results-per-page) are first-class on `ForEach` and surface to the manifest as `iterations_completed` / `iterations_capped`.
4. A new opt-in `IntegrityProbe` runs in recon mode at most once per N runs and writes findings to evidence — without the framework knowing what "integrity" means for any given site.

---

## 2. Deliverables

### 2.1 Per-site rate-limit overrides

| Path | Change |
|---|---|
| `src/gsv/config/model.py` | Add `RateLimitConfig` (`requests_per_hour: int`, `window_minutes: int = 60`); allow override under `sites.<name>.rate_limit`. |
| `src/gsv/config/loader.py` | Merge per-site overrides over visitor-level defaults. |
| `src/gsv/browser/rate_limit.py` | Accept `RateLimitConfig` instead of bare ints; existing call sites pass through. |
| `src/gsv/browser/manager.py` | Resolve effective rate-limit config from `site_config` at construction. |
| `tests/browser/test_rate_limit_overrides.py` | New: per-site override beats visitor default; missing override falls back. |

This is genuinely backward-compatible: the dataclass already exists in S1 with sensible defaults, S10 just teaches it to accept overrides without changing the call sites.

### 2.2 Pagination + platform caps

`ForEach` (S4) iterates over a selector. S10 adds two caps:

- `limit: int | None` — already exists in S4. No-op for S10.
- `pagination: PaginationConfig | None` — **new** for S10:

  ```python
  @dataclass(frozen=True)
  class PaginationConfig:
      next_button_selector: str        # "Next page" button
      max_pages: int = 10              # platform-level cap; never go beyond
      stop_when_missing: bool = True   # if next button absent, stop quietly
      pagination_dwell: tuple[float, float] = (1.5, 4.0)  # delay between pages
  ```

When `pagination` is set, `ForEach` repeats its inner block, then clicks `next_button_selector`, then re-evaluates the iteration selector — up to `max_pages` times. Each page transition emits an evidence event `pagination_advance` and increments `counters["pagination_pages"]`.

| Path | Change |
|---|---|
| `src/gsv/visit/steps.py` | Add `PaginationConfig` and integrate with `ForEach`. |
| `src/gsv/visit/runner.py` | When `ForEach.pagination` is set, the runner's per-iteration cancellation-pre / post still fires per element, plus a per-page boundary `pagination`. |
| `tests/visit/test_pagination.py` | New: caps honored, missing-next stops, dwell respected (seeded clock). |

### 2.3 Hydration-retry surfacing

The runner already calls `wait_for_selector` with retries inside `WaitFor` (S4). The retry counter exists in `VisitContext.counters["hydration_retries"]` but isn't surfaced anywhere observers look.

| Path | Change |
|---|---|
| `src/gsv/observability/recorder.py` | At `finalize()`, copy framework counter set from `VisitContext.counters` into `manifest.json["counters"]`, namespaced under `framework.*`. App counters stay under `app.*`. |
| `src/gsv/observability/manifest.py` | Document the schema in a module docstring; add a `framework_counters_version: int = 1` for future evolution. |
| `tests/observability/test_manifest_counters.py` | New: a forced hydration retry shows up as `framework.hydration_retries == 1`. |

This resolves [ARCHITECTURE.md §14 Q5](../ARCHITECTURE.md#14-open-questions) (manifest schema evolution): we keep the dict open-ended, but version the *framework-counter portion* so framework changes can bump the number without breaking app counters.

### 2.4 Integrity probe (recon-mode)

Generalized analogue of LinkedIn's panel-probe: an opt-in step that visits a stable, app-defined URL in **recon delay profile** (faster timings, no humanization), extracts a small fingerprint, and writes it to evidence. Use cases: detect site-wide structural drift, confirm the auth marker still resolves, sanity-check that the site renders at all before a long visit.

```python
@dataclass(frozen=True)
class IntegrityProbe:
    name: str                          # Probe identifier; appears in evidence
    url: str                           # Where to probe
    must_resolve: tuple[str, ...]      # Selectors that must exist
    optional_extract: tuple[Callable[[Page], Awaitable[Any]], ...] = ()
    cadence_runs: int = 10             # Run on 1-in-N runs only
    delay_profile: str = "recon"       # Always recon by default
```

| Path | Change |
|---|---|
| `src/gsv/visit/probe.py` | New module with `IntegrityProbe` and `should_run_probe(run_index, cadence)` helper. |
| `src/gsv/visit/runner.py` | Optional `probes: tuple[IntegrityProbe, ...]` argument; runner calls them at `VisitPlan` start when `should_run_probe` says yes. |
| `src/gsv/run/controller.py` | Pass run-index counter from server (or local file under `state_dir/probes_run_count`) into runner. |
| `tests/visit/test_integrity_probe.py` | New: cadence honored, recon profile applied, evidence event emitted. |

The framework provides the *machinery*; apps provide the *content*. No site-specific integrity assertions live in `gsv.*`.

### 2.5 Discoveries from S9

[S9 § 6](S09-reference-app.md#6-discoveries-feeds-s10) is expected to surface ~3-5 small gaps. This slice's task list grows by however many of those rows resolve to "yes, defer to S10". Common candidates we anticipate but don't promise:

- A `Back` step (rather than `Navigate(url='back')`).
- A way to assert "selector should NOT exist" in `WaitFor`.
- A standardized `extract_text` helper that returns "" instead of raising when an element is missing.
- A `--dry-run` flag on `gsv run` that exercises the plan without launching a browser.

Each becomes a sub-deliverable inside S10 with its own short test. Nothing here merges without the matching test.

### 2.6 Pacing extras

Two minor additions that fell out of S3 scope:

- **Per-action delay overrides on built-in steps.** `Click(selector=..., delay_profile="recon")` lets a step temporarily lower its delay. This is a five-line constructor passthrough, not a new module.
- **`Pacing.disable_for(step_label)`** — context manager that disables humanization for one labelled step (used by integrity probes).

| Path | Change |
|---|---|
| `src/gsv/visit/steps.py` | Add `delay_profile` parameter to `Click`, `Type`, `Navigate`. |
| `src/gsv/pacing/__init__.py` | Add `Pacing.disable_for(label)` context manager. |
| `tests/pacing/test_per_step_override.py` | New: a `Click(delay_profile="disabled")` runs with zero delay. |

---

## 3. Reuse map

| CE source | CE feature | Bucket | Becomes | Generalization |
|---|---|---|---|---|
| `src/scraper/jobs.py` | LinkedIn pagination caps (`MAX_PAGES_PER_SEARCH`, `MAX_RESULTS_PER_PAGE`) | **Reference** | `gsv.visit.steps.PaginationConfig` | Generic; CE numbers do not carry over (apps set their own). |
| `src/scraper/jobs.py` | Hydration retry counter increments | **Reference** | `VisitContext.counters["hydration_retries"]` already incremented in S4; S10 only surfaces it | None — already neutral. |
| `src/scraper/jobs.py` | LinkedIn panel-probe (recon visits to a known panel URL to verify structure) | **Reference** | `gsv.visit.probe.IntegrityProbe` | Strip every LinkedIn URL/selector; the framework only provides the cadence + evidence wiring. |
| `src/config.py::ScraperConfig` | Per-job-source rate-limit overrides | **Reference** | `gsv.config.model.RateLimitConfig` per-site | Rename keys to neutral; no `linkedin_rate_limit` style. |

No new copy operations — every S10 item is either Reference (read CE for shape, write fresh) or pure new code.

---

## 4. Step-by-step

### Step 10.1 — Order matters

S10 items are independent; pick whichever pairs with the developer's morning. Recommended order if no other constraint:

1. Per-site rate-limit overrides (smallest, highest leverage).
2. Hydration-retry surfacing (manifest schema lock-in — do this before more counters get added).
3. Pagination caps (medium; touches `ForEach` and the runner).
4. Integrity probe (largest; new module + new evidence event).
5. Discoveries from S9 (one PR per discovery, kept small).
6. Pacing extras (smallest; nice closer).

Each item is its own commit, all under one S10 PR.

### Step 10.2 — Schema lock-in

Before merging the manifest counter changes, add a JSON schema test that loads a fixture manifest and validates it. Future framework counter additions either:

- Add a key under `framework.*` (no schema bump needed; counters dict is open), OR
- Bump `framework_counters_version` (treated as a breaking change for downstream tooling).

`tests/observability/test_manifest_schema.py` enforces this contract.

### Step 10.3 — No surprise behavior changes

Each S10 feature ships off-by-default:

| Feature | Default state | How to enable |
|---|---|---|
| Per-site rate-limit override | Off (no override → visitor default applies) | Add `sites.<name>.rate_limit` to YAML |
| Pagination | Off (`ForEach.pagination is None`) | Pass `pagination=PaginationConfig(...)` |
| Integrity probe | Off (no probes registered) | Pass `probes=(...)` to `VisitRunner` |
| Per-step delay override | Off (`delay_profile=None`) | Pass `delay_profile="recon"` etc. |
| `Pacing.disable_for` | Off (no-op unless used) | Wrap an inner block in the context manager |

This is the "compatible with apps that don't opt in" constraint and it is verified by re-running [`apps/example/`](S09-reference-app.md) before/after the slice; the manifest deltas should be zero.

### Step 10.4 — Documentation pass

S10 is the last slice, so it's also the doc-cleanup slice:

- Update [ARCHITECTURE.md §12 Roadmap](../ARCHITECTURE.md#12-roadmap): mark S1–S10 done; promote v1 candidates from "Out of scope".
- Update [ARCHITECTURE.md §14 Open questions](../ARCHITECTURE.md#14-open-questions): tick Q5 (manifest schema), and any others S10 actually resolved.
- Update [IMPLEMENTATION_PLAN.md § 8](../IMPLEMENTATION_PLAN.md#8-open-questions) accordingly.
- Add a `CHANGELOG.md` entry covering the v0 set; this is the first release.
- Add a one-paragraph "what's next" section to [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) pointing at the v1 candidates.

---

## 5. Acceptance criteria

- [ ] `pytest tests/` green; coverage ≥ 90% on touched modules; ≥ 95% on `gsv.visit.probe` (it's small and pure).
- [ ] `apps/example/` runs identically before and after the slice (manifest counter sets equal except for any new keys under `framework.*`).
- [ ] `manifest.json` includes a `framework_counters_version: 1` field.
- [ ] Per-site rate-limit override demonstrated in a test: setting `requests_per_hour: 30` for site `example` yields a `RateLimiter` initialized with 30, while the visitor default of 60 stays for other sites.
- [ ] `ForEach(pagination=...)` advances at most `max_pages` pages; evidence shows one `pagination_advance` per advance.
- [ ] `IntegrityProbe(cadence_runs=10)` runs on exactly 1 of every 10 runs (verified with deterministic counter).
- [ ] At least 3 of the [S9 § 6 Discoveries](S09-reference-app.md#6-discoveries-feeds-s10) rows are addressed; remaining rows are closed with "won't do" + rationale or moved to a follow-up issue.
- [ ] [ARCHITECTURE.md](../ARCHITECTURE.md) and [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) reflect the post-S10 state.

---

## 6. Out of scope (deferred to v1)

- Multi-site session pool inside one worker.
- Proxy rotation.
- Distributed worker coordination.
- Postgres / production-grade control plane.
- A web UI for sessions.
- Per-app KV store ([ARCHITECTURE.md §14 Q7](../ARCHITECTURE.md#14-open-questions)) — revisit after a second app exists.
- CAPTCHA solving.

---

## 7. Dependencies

- Upstream: **S9** (its discoveries set part of this slice's scope).
- Downstream blockers: none — S10 is the v0 finish line.

---

## 8. Open questions

| ID | Question | Recommendation | Resolve in |
|---|---|---|---|
| Q1 | Should `framework_counters_version` go in the manifest, or in a sibling file? | In the manifest. Single artifact = single read for downstream tooling. | S10 |
| Q2 | Where does the "runs since last probe" counter live for cadence enforcement? | Local file under `state_dir/probes/<probe-name>.count`. Server doesn't need to know. | S10 |
| Q3 | Per-step `delay_profile` override: is this a maintainability footgun? | Likely yes if abused. Document as "for explicit recon/audit use only"; flake8 rule optional. | S10 |
| Q4 | Should pagination dwell timing borrow from the burst governor or be independent? | Independent. Pagination is a step-internal pause, not a between-action one. | S10 |

---

## 9. Reviewer checklist

- [ ] No new feature is on by default; all are opt-in via config or constructor argument.
- [ ] Every S10 module has tests at ≥ 90% coverage.
- [ ] No `linkedin`, `vps`, `panel_probe`, `job`, `company` strings in any new code.
- [ ] [S9 § 6 Discoveries](S09-reference-app.md#6-discoveries-feeds-s10) table is fully resolved (each row has either a commit reference, a "won't do" rationale, or a follow-up issue link).
- [ ] [ARCHITECTURE.md §12 Roadmap](../ARCHITECTURE.md#12-roadmap) reflects v0 complete.
- [ ] `CHANGELOG.md` exists with a v0.1.0 entry.
- [ ] `apps/example/` re-run before/after produces equivalent manifests (counters dict is a superset, never different values).
