# gsv.server.dev

`gsv server dev` is a SQLite-backed reference coordination API for local
development and tests. Production deployments should swap this service for
their own API while preserving the `gsv.run` HTTP contract.

## Security

All API and admin endpoints require an API key. The server accepts either
`X-API-Key: <key>` or `Authorization: Bearer <key>`. `GSV_API_KEY` controls the
key; the CLI defaults it to `dev` only when starting the local dev server.

## Schema

```sql
CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    plan_name TEXT NOT NULL,
    site TEXT NOT NULL,
    parameters TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    cancel_reason TEXT,
    claimed_by TEXT,
    claimed_at INTEGER,
    submitted_at INTEGER,
    outcome TEXT,
    result_payload TEXT,
    error TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE leases (
    worker_id TEXT PRIMARY KEY,
    lease_token TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    last_heartbeat INTEGER NOT NULL
);

CREATE TABLE cancellation_acks (
    run_id TEXT PRIMARY KEY,
    partials TEXT NOT NULL,
    received_at INTEGER NOT NULL
);
```

## Endpoints

Worker contract:

```text
POST /api/worker/lease/register
POST /api/worker/lease/heartbeat
POST /api/worker/lease/release
POST /api/runs/next/claim
POST /api/runs/{id}/claim
GET  /api/runs/{id}/control
POST /api/runs/{id}/submit
POST /api/runs/{id}/cancellation_ack
```

Local/admin helpers:

```text
POST /api/runs
GET  /api/runs/next
POST /api/runs/{id}/heartbeat
POST /api/runs/{id}/complete
POST /api/runs/{id}/fail
POST /api/runs/{id}/cancel
GET  /api/runs/{id}/status
POST /admin/runs
POST /admin/runs/{id}/cancel
GET  /admin/runs
```
