## Barebones FastAPI (`/api`)

This folder contains a minimal FastAPI service managed by **uv**.

### Local dev

- **Install uv** (if you don't have it):
  - `curl -LsSf https://astral.sh/uv/install.sh | sh`

- **Create venv + install deps**:
  - `cd api`
  - `uv sync`

- **Run the API**:
  - `uv run uvicorn oracle_tutor_api.main:app --reload --host 0.0.0.0 --port 8000`

### Production / Railway env vars

- **DATABASE_URL**: required in production (and on Railway). Prefer using Railway Postgres' provided connection string.
- **ORACLE_TUTOR_API_ENV**: set to `production` in production. (If you forget this on Railway, the app still treats Railway as production to avoid insecure defaults.)
- **ORACLE_TUTOR_API_UPDATE_ENABLED**: recommended `false` on the API service; run scheduled ingestion in a separate worker service instead.
- **ORACLE_TUTOR_API_CORS_ORIGINS**: leave unset for same-origin. If you need cross-origin access, set a comma-separated allowlist.

### One-shot worker (Railway Cron)

The worker is designed to be run as a **one-time command** (cron-friendly): it runs the stale-aware update once and exits.

- **Command**:
  - `python -m oracle_tutor_api.worker --strict --trigger-type cron`

### Tests

- **Install test deps**:
  - `cd api`
  - `uv sync --group test`

- **Run**:
  - `uv run pytest`

Endpoints:
- `GET /` -> basic service info
- `GET /health` -> health check

### Docker

From the repo root:

- **Build**:
  - `docker build -t oracle-tutor-api -f api/Dockerfile api`

- **Run**:
  - `docker run --rm -p 8000:8000 oracle-tutor-api`

### Railway (production)

Recommended environment variables:

- `ORACLE_TUTOR_API_ENV=production`
- `DATABASE_URL=...` (from Railway Postgres)
- `ORACLE_TUTOR_API_UPDATE_ENABLED=false` (run updates in the worker service instead)
 - `PORT` is injected by Railway automatically; the Dockerfile listens on it.

Optional:

- `ORACLE_TUTOR_API_CORS_ORIGINS=` (comma-separated origins; leave unset for same-origin deployments)


