## Barebones FastAPI (`/api`)

This folder contains a minimal FastAPI service managed by **uv**.

### Local dev

- **Install uv** (if you don't have it):
  - `curl -LsSf https://astral.sh/uv/install.sh | sh`

- **Create venv + install deps**:
  - `cd api`
  - `uv sync --extra api --extra worker`

- **Run the API**:
  - `uv run hypercorn oracle_tutor_api.api.main:app --reload --bind 0.0.0.0:8000`

- **Ingest/update data (one-shot worker)**:
  - `uv run python -m oracle_tutor_api.worker.main --strict --trigger-type manual`

### Production / Railway env vars

- **DATABASE_URL**: required in production (and on Railway). Prefer using Railway Postgres' provided connection string.
- **ORACLE_TUTOR_API_ENV**: set to `production` in production. (If you forget this on Railway, the app still treats Railway as production to avoid insecure defaults.)
- **ORACLE_TUTOR_API_CORS_ORIGINS**: leave unset for same-origin. If you need cross-origin access, set a comma-separated allowlist.

### Database configuration precedence

- **Production / Railway**: set `DATABASE_URL` (required; the API refuses to start without it in production).
- **Local/dev**: you can either set `DATABASE_URL`, or set `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` (see `src/oracle_tutor_api/core/database.py`).

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
 - `PORT` is injected by Railway automatically; the Dockerfile listens on it.

Optional:

- `ORACLE_TUTOR_API_CORS_ORIGINS=` (comma-separated origins; leave unset for same-origin deployments)


