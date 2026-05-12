# Backend (`/backend`)

FastAPI service for Oracle Tutor, plus an ingest-worker cron service. Dataset generation, training, and promotion are now operator-run local scripts under `backend/scripts/`.

## Local setup

```bash
cd backend
uv sync --all-extras --group dev
```

If you only need a subset of dependencies:

- API only: `uv sync --extra api`
- Ingestion worker only: `uv sync --extra scryfall-sync`
- Semantic training: `uv sync --extra semantic-train`

## Local commands

Run the API:

```bash
uv run hypercorn ot_backend.api.main:app --reload --bind 0.0.0.0:8000
```

Quality checks:

```bash
uv run ruff check src/ --fix
uv run basedpyright src/
uv run pytest -x -q   # requires Docker running; tests spin up a pgvector container via testcontainers
```

Apply migrations directly (requires `DATABASE_URL`):

```bash
DATABASE_URL=postgresql+psycopg://oracle:secret_password@localhost/mtg_search \
  uv run alembic upgrade head
```

## API runtime behavior

- API startup runs DB initialization under a session-level `pg_advisory_lock` (held across Alembic), then waits for schema migration readiness.
- API startup queries the semantic model registry for an active model; loads its ONNX bundle from S3 if found.
- If no active model exists in the registry, semantic endpoints return `503`.
- Model bundles are cached locally in `SEMANTIC_TEMP_DIR` (default: system temp dir).
- The lifespan task `rotate_oracle_pools` refreshes the homepage oracle-text / keyword samples every `OT_ORACLE_POOL_REFRESH_SECONDS`.

Core routes:

- `GET /`
- `GET /health`
- `GET /version`
- `GET /oracle-samples`
- `GET /search?q=...`
- `GET /card/{oracle_id}`
- `GET /similar-cards?oracle_id=...`
- `GET /similar-cards?q=...`

Admin auth:

- Every `/admin/*` route (including `POST /admin/auth/token`) first runs a **Cloudflare Access JWT check**. The dep reads `Cf-Access-Jwt-Assertion` (header) or `CF_Authorization` (cookie), fetches the Cloudflare JWKS at `https://<CF_ACCESS_TEAM_DOMAIN>/cdn-cgi/access/certs`, and verifies RS256 + audience (`CF_ACCESS_AUD`) + issuer. Invalid or missing token → `403`.
- The check is **bypassed** only when both `CF_ACCESS_TEAM_DOMAIN` and `CF_ACCESS_AUD` are unset *and* the API is not running in production (`OT_ENV=production` or any `RAILWAY_*` env var present). In production with those unset, every admin request returns `503 "Cloudflare Access is not configured"` — fail-closed.
- `POST /admin/auth/token` exchanges the configured admin password for an 8-hour bearer token. Password compare uses `hmac.compare_digest` (constant-time). This runs *after* the Cloudflare check.
- The frontend nginx proxy additionally rate-limits `POST /api/admin/auth/token` per source IP, and returns `404` for any `/admin/*` or `/api/admin/*` request whose `Host` header isn't the configured `ADMIN_HOST` — so the admin surface is invisible on the public hostname.
- Failed admin login attempts are tracked per source IP in process memory.
- After `ADMIN_LOGIN_MAX_FAILURES` consecutive failures from the same IP, that IP is locked out for `ADMIN_LOGIN_LOCKOUT_SECONDS`.
- A successful login clears the failure counter for that IP.
- Request IP resolution prefers `X-Real-IP`, then `X-Forwarded-For`, then the socket peer.
- If you run behind a proxy, it must set `X-Real-IP` itself and sanitize any inbound forwarded-IP headers.

Admin routes:

- `POST /admin/auth/token`
- `GET /admin/semantic-models`
- `POST /admin/semantic-models` — upload a model bundle (zip body)
- `GET /admin/semantic-models/{model_id}`
- `GET /admin/semantic-models/{model_id}/artifacts`
- `POST /admin/semantic-models/{model_id}/promote`

## `ingest-worker`

`ingest-worker` is a one-shot worker intended for local manual runs and Railway Cron.

Base command:

```bash
uv run python -m ot_backend.ingest.main --strict --trigger-type manual
```

Available flags:

- `--force`: force download and re-ingestion even if metadata says the DB is current
- `--refresh-tags`: force a full Scryfall Tagger refresh after card ingestion
- `--skip-tags`: skip community tag ingestion entirely
- `--trigger-type <value>`: label the ingestion run in logs and metadata
- `--strict`: exit non-zero on metadata/download failures instead of treating them as a noop

Current ingestion flow:

1. Check schema readiness and refuse to run if migrations are not ready.
2. Fetch remote Scryfall bulk metadata.
3. Compare remote metadata against local bulk metadata and DB metadata.
4. Skip download and card ingestion entirely when the DB already matches the latest remote timestamp.
5. When work is needed, download the latest Oracle Cards bulk file and diff-ingest it into:
   `cards_raw`, `cards`, and `card_faces` (including `type_categories` extracted from `type_line`). The delete phase runs inside a single transaction so a crash cannot leave orphan rows.
6. Refresh community tags in parallel (default 6 workers, tunable via `TAG_FETCH_CONCURRENCY`) unless `--skip-tags` is set. Each worker thread owns its own `requests.Session` + CSRF token; a 429 on one session doesn't invalidate the others.

Examples:

```bash
# Force a full run
uv run python -m ot_backend.ingest.main --force --strict --trigger-type manual

# Refresh tags for every card
uv run python -m ot_backend.ingest.main --refresh-tags --strict --trigger-type manual

# Load card data only
uv run python -m ot_backend.ingest.main --skip-tags --strict --trigger-type manual
```

### Railway Cron

The worker is designed to run once and exit:

```bash
python -m ot_backend.ingest.main --strict --trigger-type cron
```

`backend/Dockerfile.worker.ingest` already uses that command as its container `CMD`.

## Local scripts (`backend/scripts/`)

Dataset generation, training, and model promotion are now driven by operator-run local scripts instead of a job-queue system. These scripts replace the old `dataset-worker`, `train-worker`, and `promotion-worker` containers.

Available scripts:

- `build_dataset.py` — builds and registers a training dataset from cards in the DB
- `train_model.py` — fine-tunes (or base-model trains) via Modal, exports ONNX, bundles, and registers the model
- `promote_model.py` — materializes the bundle and computes embeddings in a single transaction, then activates the model

Typical workflow:

```bash
# Build a new dataset
uv run python -m scripts.build_dataset --name v3-balanced

# Train on that dataset (requires Modal credentials)
uv run python -m scripts.train_model --dataset-id <id> --slug v3 --base-model all-MiniLM-L6-v2

# Promote the trained model
uv run python -m scripts.promote_model --model-id <id>
```

All three scripts accept `--prod` to target the production Railway database (reads `.env.prod` from repo root if present).

`train_model.py` also accepts `--skip-fine-tune` to skip Modal training and register a base model directly (no remote job).

## Model training via Modal

`train_model.py` calls into `ot_backend.semantic.modal_train` via `modal.Function.lookup`, which provisions a Modal job and streams the training logs. The script waits for the job to complete, then writes the final model bundle and metadata to the DB. This replaces the prior "POST → worker picks up" async flow.

## Environment variables

### Database and runtime

- `DATABASE_URL`: required everywhere (production, local, alembic CLI); must point at Postgres with pgvector
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`: local DB settings when `DATABASE_URL` is absent
- `OT_ENV`: `development` or `production`
- `OT_SERVICE_ROLE`: `api` (default) or `worker` — sizes DB pool defaults
- `DB_POOL_SIZE` / `DB_POOL_MAX_OVERFLOW`: override role defaults (`10+5` for api, `2+1` for workers)
- `ADMIN_PASSWORD`: password accepted by `POST /admin/auth/token`
- `ADMIN_JWT_SECRET`: HS256 signing secret for admin bearer tokens
- `ADMIN_LOGIN_MAX_FAILURES`: consecutive failed admin logins per IP before lockout; defaults to `5`
- `ADMIN_LOGIN_LOCKOUT_SECONDS`: lockout duration after hitting the failure threshold; defaults to `900`
- `CF_ACCESS_TEAM_DOMAIN`: Cloudflare Access team domain (e.g. `yourteam.cloudflareaccess.com`); required together with `CF_ACCESS_AUD` in production — when unset in production, every `/admin/*` request returns `503`
- `CF_ACCESS_AUD`: Cloudflare Access application AUD tag; paired with `CF_ACCESS_TEAM_DOMAIN` to enable JWT verification on `/admin/*`
- `OT_CORS_ORIGINS`: optional comma-separated allowlist
- `OT_SCHEMA_WAIT_TIMEOUT_SECONDS`: API startup wait budget for schema readiness
- `OT_SCHEMA_WAIT_INTERVAL_SECONDS`: polling interval while waiting for schema readiness
- `OT_ORACLE_POOL_REFRESH_SECONDS`: how often the lifespan refreshes the homepage pools; defaults to `600`

### Semantic model and caches

- `HF_HOME`: Hugging Face cache directory; defaults to `data/huggingface`
- `SEMANTIC_ARTIFACT_ENDPOINT`: S3-compatible endpoint URL for model artifact storage
- `SEMANTIC_ARTIFACT_ACCESS_KEY_ID`: S3 access key ID
- `SEMANTIC_ARTIFACT_SECRET_ACCESS_KEY`: S3 secret access key
- `SEMANTIC_ARTIFACT_REGION`: S3 region; defaults to `auto`
- `SEMANTIC_ARTIFACT_BUCKET`: S3 bucket name for model artifacts
- `SEMANTIC_TEMP_DIR`: local cache directory for materialized model bundles
- `SEMANTIC_ACTIVE_MODEL_POLL_SECONDS`: how often the API polls for a new active model; defaults to `5`
- `SEMANTIC_ONNX_INTRA_OP_THREADS`: ONNX Runtime intra-op threads; defaults to `1`
- `SEMANTIC_ONNX_INTER_OP_THREADS`: ONNX Runtime inter-op threads; defaults to `1`

### Ingestion

- `TAG_FETCH_CONCURRENCY`: parallel Scryfall Tagger workers; defaults to `6`

## Schema reset / destructive flows

- API startup is non-destructive and waits for schema readiness.
- The codebase has been squashed to a single `0001_initial_schema.py`. Starting from a fresh DB runs exactly that one migration.
- For breaking schema changes going forward, add a new Alembic revision (`0002_*.py`) with its migration logic; do not modify the initial migration.

## Docker

From the repo root:

```bash
docker compose up --build
```

That stack starts `db`, `minio`, `api`, and `frontend`. The `ingest-worker` service is defined under the `manual` profile in `docker-compose.yml` and is not started by default; invoke it explicitly:

```bash
docker compose run --rm ingest-worker
```
