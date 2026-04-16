# Backend (`/backend`)

FastAPI service for Oracle Tutor, plus the one-shot ingestion worker and the offline semantic training pipeline.

## Local setup

```bash
cd backend
uv sync --all-extras --group dev
```

If you only need a subset of dependencies:

- API only: `uv sync --extra api`
- Ingestion worker only: `uv sync --extra scryfall-sync`
- Semantic pipeline only: `uv sync --extra oracle-embed`

## Local commands

Run the API:

```bash
uv run hypercorn ot_backend.api.main:app --reload --bind 0.0.0.0:8000
```

Quality checks:

```bash
uv run ruff check src/ --fix
uv run basedpyright src/
uv run pytest -x -q
```

Apply migrations directly:

```bash
uv run alembic upgrade head
```

## API runtime behavior

- API startup runs DB initialization and waits for schema migration readiness.
- API startup queries the semantic model registry for an active model; loads its ONNX bundle from S3 if found.
- If no active model exists in the registry, semantic endpoints return `503`.
- Model bundles are cached locally in `SEMANTIC_TEMP_DIR` (default: system temp dir).

Core routes:

- `GET /`
- `GET /health`
- `GET /version`
- `GET /oracle-samples`
- `GET /search?q=...`
- `GET /card/{oracle_id}`
- `GET /similar-cards?oracle_id=...`
- `GET /similar-cards?q=...`
- `POST /telemetry/client-error`
- `POST /telemetry/analytics`

Admin auth:

- `POST /admin/auth/token` exchanges the configured admin password for an 8-hour bearer token.
- The frontend nginx proxy also rate-limits `POST /api/admin/auth/token` per source IP before the request reaches the API.
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
- `GET /admin/semantic-jobs`
- `GET /admin/semantic-jobs/{job_id}`
- `POST /admin/semantic-jobs/train`
- `POST /admin/semantic-jobs/promote`

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
   `cards_raw`, `cards`, and `card_faces`.
6. Recompute card uniqueness scores.
7. Refresh community tags unless `--skip-tags` is set.

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

The current `backend/Dockerfile.ingest-worker` already uses that command as its container `CMD`.

## `promotion-worker`

`promotion-worker` runs pending promote jobs from the `semantic_jobs` table. It downloads the model bundle from S3, populates `semantic_model_embeddings`, and activates the model.

Base command:

```bash
uv run python -m ot_backend.semantic.promote_worker
```

Available flags:

- `--job-id <id>`: run a specific job by ID instead of claiming the next pending one

The worker is designed to run once and exit. Multiple promote jobs will be processed in sequence up to `SEMANTIC_PROMOTE_MAX_JOBS_PER_RUN`.

## Semantic pipeline

The semantic pipeline (`src/ot_backend/semantic/pipeline.py`) is an offline workflow: dataset export, model fine-tuning, ONNX export, and bundle creation. After running it, register the resulting bundle via the admin API or `register_model_bundle_bytes`.

Base command:

```bash
uv run python -m ot_backend.semantic.pipeline
```

What it does on a normal run:

1. Build a dataset from normalized `card_faces` text, self-pairs, community tag pairs, tag-description pairs, generated template queries, and optional LLM-generated query pairs.
2. Fine-tune a sentence-transformer model unless `--no-fine-tune` is set.
3. Export ONNX artifacts for API inference.
4. Bundle the run directory into a zip for upload to the registry.

Useful commands:

```bash
# Full train + ONNX export
uv run python -m ot_backend.semantic.pipeline

# Use the base model without fine-tuning
uv run python -m ot_backend.semantic.pipeline --no-fine-tune

# Export only the dataset
uv run python -m ot_backend.semantic.pipeline --export-dataset data/training-dataset.json

# Evaluate against scripted queries
uv run python -m ot_backend.semantic.pipeline --eval
```

Artifacts are stored under `data/semantic/runs/<run-id>/`. After a run, upload the bundle to the registry with `POST /admin/semantic-models` and promote it with `POST /admin/semantic-models/{id}/promote`.

## Environment variables

### Database and runtime

- `DATABASE_URL`: required in production; overrides `DB_*`
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`: local DB settings when `DATABASE_URL` is absent
- `OT_ENV`: `development` or `production`
- `ADMIN_PASSWORD`: password accepted by `POST /admin/auth/token`
- `ADMIN_JWT_SECRET`: HS256 signing secret for admin bearer tokens
- `ADMIN_LOGIN_MAX_FAILURES`: consecutive failed admin logins per IP before lockout; defaults to `5`
- `ADMIN_LOGIN_LOCKOUT_SECONDS`: lockout duration after hitting the failure threshold; defaults to `900`
- `OT_CORS_ORIGINS`: optional comma-separated allowlist
- `OT_ALLOW_SCHEMA_RESET`: must be explicitly `true` to allow destructive schema reset flows
- `OT_SCHEMA_WAIT_TIMEOUT_SECONDS`: API startup wait budget for schema readiness
- `OT_SCHEMA_WAIT_INTERVAL_SECONDS`: polling interval while waiting for schema readiness

### Semantic model and caches

- `SEMANTIC_BASE_MODEL`: base Hugging Face model ID; defaults to `sentence-transformers/all-MiniLM-L6-v2`
- `SEMANTIC_RUNS_DIR`: optional override for semantic pipeline run output root
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
- `SEMANTIC_JOB_HEARTBEAT_SECONDS`: heartbeat interval for promotion worker; defaults to `600`
- `SEMANTIC_JOB_STALE_SECONDS`: seconds before a running job is declared stale; defaults to `1200`
- `SEMANTIC_PROMOTE_MAX_JOBS_PER_RUN`: max promote jobs per worker run; defaults to `50`

## Schema reset runbook

- API startup is non-destructive and waits for schema readiness.
- Destructive schema reset flows are guarded behind `OT_ALLOW_SCHEMA_RESET=true`.
- For schema major/minor bumps:
  1. Temporarily enable `OT_ALLOW_SCHEMA_RESET=true` on the ingestion worker.
  2. Run `ingest-worker` once and confirm it completes successfully.
  3. Disable the reset flag again.
  4. Start or restart the API after migration state is `ready`.
- If migration state becomes `failed`, fix the worker/migration issue before repeatedly restarting the API.

## Docker

From the repo root:

```bash
docker compose up --build
```

That stack starts `db`, `api`, `frontend`, and the one-shot `ingest-worker` service. If you want local app services without running ingestion immediately:

```bash
docker compose up --build db api frontend
```
