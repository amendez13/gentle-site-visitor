# Example app

Reference Gentle Site Visitor app demonstrating an end-to-end gentle visit
against Wikipedia's list of exceptional asteroids.

## What it does

The app opens the public list page for exceptional asteroids, extracts asteroid
article links from the main table, visits each asteroid article, and records the
composition or spectral type from the article infobox when present. Evidence is
written as one `asteroid_extracted` event per visited asteroid plus a final
`visit_complete` summary.

## Why this site

Wikipedia is public, stable, and has consistent article infobox structure. Its
robots file documents that friendly, low-speed bots may view article pages and
disallows dynamic `/w/`, `/api/`, trap, and special-page paths:
<https://en.wikipedia.org/robots.txt>. This app stays on article URLs under
`/wiki/`. The default app config keeps the conservative framework cap of
`rate_limit_per_hour: 90`, with short per-action delays and small burst
cooldowns so bounded headed demos visibly move through pages without stalling
for minutes. Lower `GSV_EXAMPLE_RATE_LIMIT_PER_HOUR` and raise
`GSV_EXAMPLE_DELAY_MIN/MAX` for slower unattended runs.

This is an interactive reference app, not a bulk crawler. By default, live runs
visit up to 20 asteroid pages. Set `GSV_EXAMPLE_LIMIT` to a positive integer to
choose a different cap, or `0` to disable the cap.

## Running

```bash
gsv --config apps/example/config.yaml config validate --site example
gsv --config apps/example/config.yaml run example --once --headed --observability=always
gsv --config apps/example/config.yaml sessions list --site example
gsv --config apps/example/config.yaml sessions inspect --site example --latest
gsv --config apps/example/config.yaml plan show --site example --date 2026-05-05 --seed 42
```

For a faster manual smoke run while preserving the same plan shape:

```bash
GSV_EXAMPLE_LIMIT=20 \
GSV_EXAMPLE_DELAY_MIN=0 \
GSV_EXAMPLE_DELAY_MAX=0 \
GSV_EXAMPLE_DISTRACTION_CHANCE=0 \
GSV_EXAMPLE_RATE_LIMIT_PER_HOUR=999 \
GSV_EXAMPLE_BURST_MIN=0.01 \
GSV_EXAMPLE_BURST_MAX=0.01 \
GSV_EXAMPLE_ARTICLE_DWELL_MIN=0 \
GSV_EXAMPLE_ARTICLE_DWELL_MAX=0 \
GSV_EXAMPLE_DWELL_MIN=0 \
GSV_EXAMPLE_DWELL_MAX=0 \
GSV_EXAMPLE_TRACE=false \
gsv --config apps/example/config.yaml run example --once --observability=always
```

The normal headed demo keeps each asteroid article visible for an 8-10 second
skim/read cycle: navigate to the article, extract the infobox composition,
scroll the article, dwell visibly, record evidence, and continue to the next
stored article URL.

## Expected output

- `manifest.json` has `outcome: completed`.
- `counters.actions_total` is greater than zero.
- `counters.cooldowns` is at least one when the burst interval is reached.
- `counters.hydration_retries` may be zero; the plan enables per-item hydration
  retry but Wikipedia usually serves article HTML synchronously.
- `evidence.jsonl` contains rows with `event_type: asteroid_extracted` and
  `payload` fields for `name`, `url`, and `composition`, followed by a
  `visit_complete` event with `total`, `visited`, `extracted`, and `missing`.

## Adapting for your own site

Keep site selectors in `selectors.py`, page-specific parsing in
`extractors.py`, and the workflow in `visit.py`. Apps compose framework steps
rather than modifying `src/gsv`. See
[ARCHITECTURE.md section 10](../../docs/ARCHITECTURE.md#10-reference-application-contract).
