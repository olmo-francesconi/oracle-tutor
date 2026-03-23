## Barebones FastAPI (`/backend`)

This folder contains a minimal FastAPI service managed by **uv**.

### Local dev

- **Install uv** (if you don't have it):
  - `curl -LsSf https://astral.sh/uv/install.sh | sh`

- **Create venv + install deps**:
  - `cd backend`
  - `uv sync --extra api --extra worker`

- **Run the API**:
  - `uv run hypercorn ot_backend.api.main:app --reload --bind 0.0.0.0:8000`

- **Ingest/update data (one-shot worker)**:
  - `uv run python -m ot_backend.ingest.main --strict --trigger-type manual`

### Production / Railway env vars

- **DATABASE_URL**: required in production (and on Railway). Prefer using Railway Postgres' provided connection string.
- **ORACLE_TUTOR_API_ENV**: set to `production` in production. (If you forget this on Railway, the app still treats Railway as production to avoid insecure defaults.)
- **ORACLE_TUTOR_API_CORS_ORIGINS**: leave unset for same-origin. If you need cross-origin access, set a comma-separated allowlist.
- **ORACLE_TUTOR_API_ALLOW_SCHEMA_RESET**: defaults to `false`. Must be explicitly set to `true` for destructive table resets when schema major/minor changes.
- **ORACLE_TUTOR_API_SCHEMA_WAIT_TIMEOUT_SECONDS**: API startup wait budget for schema migration state (default: `30`).
- **ORACLE_TUTOR_API_SCHEMA_WAIT_INTERVAL_SECONDS**: polling interval while waiting for migration readiness (default: `1`).
- **ORACLE_TUTOR_API_WORKER_TOKEN**: shared secret required for worker-only internal TF-IDF rebuild endpoint.
- **ORACLE_TUTOR_API_WORKER_TRIGGER_ALLOWLIST**: comma-separated internal hosts/IPs/domains allowed to call worker internal endpoint. Hostnames (e.g. `worker.railway.internal`) are DNS-resolved at request time to compare against the client IP, so you can allowlist by hostname even when requests arrive as IPs.
- **ORACLE_TUTOR_API_WORKER_REBUILD_PATH**: internal rebuild endpoint path (default: `/internal/rebuild-tfidf`).
- **ORACLE_TUTOR_API_WORKER_REBUILD_TIMEOUT_SECONDS**: worker HTTP timeout for rebuild trigger call (default: `10`).
- **ORACLE_TUTOR_API_BASE_URL**: API base URL used by worker to call internal rebuild endpoint (e.g. `http://api:8000`).

### Database configuration precedence

- **Production / Railway**: set `DATABASE_URL` (required; the API refuses to start without it in production).
- **Local/dev**: you can either set `DATABASE_URL`, or set `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` (see `src/ot_backend/core/database.py`).

### One-shot worker (Railway Cron)

The worker is designed to be run as a **one-time command** (cron-friendly): it runs the stale-aware update once and exits.

- **Command**:
  - `python -m ot_backend.ingest.main --strict --trigger-type cron`

- **Optional immediate TF-IDF refresh trigger**:
  - Worker posts to API internal endpoint after successful ingestion.
  - Configure:
    - `ORACLE_TUTOR_API_BASE_URL=http://api:8000`
    - `ORACLE_TUTOR_API_WORKER_TOKEN=<shared-secret>`
    - `ORACLE_TUTOR_API_WORKER_TRIGGER_ALLOWLIST=api,127.0.0.1,testclient` (example)
  - Trigger is best-effort: ingestion success is not rolled back if trigger fails.
  - During an active TF-IDF rebuild, TF-IDF-backed query endpoints intentionally return `503`.
  - Rebuild uses copy-on-write and swaps the new index into active use only after successful completion.

### Schema migration safety / runbook

- API startup is non-destructive and waits for schema migration readiness.
- Worker owns destructive schema resets and guards them behind `ORACLE_TUTOR_API_ALLOW_SCHEMA_RESET=true`.
- For schema major/minor bumps:
  1. Temporarily enable `ORACLE_TUTOR_API_ALLOW_SCHEMA_RESET=true` on worker.
  2. Run worker once and confirm successful completion.
  3. Disable the reset flag again.
  4. Start/restart API after migration state is `ready`.
- If migration state becomes `failed`, do not restart API repeatedly until worker logs are fixed and migration rerun.
- Worker-triggered TF-IDF rebuild is additive; API still has metadata-based periodic refresh as fallback.

### Tests

- **Install test deps**:
  - `cd backend`
  - `uv sync --group test`

- **Run**:
  - `uv run pytest`

Endpoints:
- `GET /` -> basic service info
- `GET /health` -> health check

### Docker

From the repo root:

- **Build**:
  - `docker build -t oracle-tutor-api -f backend/Dockerfile backend`

- **Run**:
  - `docker run --rm -p 8000:8000 oracle-tutor-api`

### Railway (production)

Recommended environment variables:

- `ORACLE_TUTOR_API_ENV=production`
- `DATABASE_URL=...` (from Railway Postgres)
 - `PORT` is injected by Railway automatically; the Dockerfile listens on it.

Optional:

- `ORACLE_TUTOR_API_CORS_ORIGINS=` (comma-separated origins; leave unset for same-origin deployments)
