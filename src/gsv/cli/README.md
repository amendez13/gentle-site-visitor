# gsv CLI

The Click-based operator surface can run local visits, inspect session bundles,
validate config, inspect schedules, and drive the coordinated worker/dev server.

## Commands

```bash
gsv --version
gsv config validate --site example
gsv run example --once --headed --observability=always
gsv sessions list --site example
gsv sessions inspect --site example --latest
gsv sessions open --site example --latest
gsv sessions purge --site example --older-than 14 --keep 100 --dry-run
gsv plan show --site example --date 2026-05-04 --seed 42
GSV_API_KEY=dev gsv server dev --port 8085
gsv worker --site example --once
gsv worker --site example --schedule
```

`gsv run` is a single in-process visit driver without lease coordination.
`gsv worker` registers a lease, claims pending runs from the coordination API,
polls cooperative cancellation through the visit runner, and submits terminal
outcomes. `gsv worker --schedule` computes the YAML-backed daily plan, waits
until each non-skipped slot, creates a pending run for that profile, and claims
that exact run id before execution. With `--once`, scheduled mode executes only
the next non-skipped slot for the scheduler's local day and exits.

`gsv plan show` prints the computed daily schedule. Use `--seed` for
reproducible jitter and `--json` for automation.

## Session Directories

By default, sessions are grouped per site:

```text
<visitor.observability.sessions_dir>/<site>/<UTC-stamp>_run-<id>/
```

Use `--sessions-dir` on `gsv sessions ...` commands to inspect a specific
directory directly.

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Runtime or visit failure |
| `10` | Authentication failure |
| `20` | Configuration error |
