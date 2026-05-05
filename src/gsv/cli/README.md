# gsv CLI

S6 ships the Click-based operator surface for slices S1-S5.

## Commands

```bash
gsv --version
gsv config validate --site example
gsv run example --once --headed --observability=always
gsv sessions list --site example
gsv sessions inspect --site example --latest
gsv sessions open --site example --latest
gsv sessions purge --site example --older-than 14 --keep 100 --dry-run
gsv plan show --site example
```

`gsv run` is a single in-process visit driver in S6. It does not claim leases,
poll cancellation, or run schedules; S7 and S8 layer those behaviors in.

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

`gsv plan show` is a placeholder in S6. It exits 0 and prints that schedule
integration arrives in S8.
