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
- API startup also attempts to load the semantic ONNX model from `SEMANTIC_MODEL_PATH`.
- If the semantic model is unavailable, semantic endpoints return `503` until artifacts are present.
- The default semantic model location is `data/semantic/runs/latest/models/onnx`.

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

## `scryfall-sync`

`scryfall-sync` is a one-shot worker intended for local manual runs and Railway Cron.

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

The current `backend/Dockerfile.scryfall-sync` already uses that command as its container `CMD`.

## Semantic pipeline

The semantic pipeline lives in `src/ot_backend/embed/pipeline.py`. It is an offline workflow for dataset export, model training, ONNX export, embedding computation, and evaluation.

Base command:

```bash
uv run python -m ot_backend.embed.pipeline
```

What it does on a normal run:

1. Build a dataset from normalized `card_faces` text, self-pairs, community tag pairs, tag-description pairs, and generated template queries.
2. Fine-tune a sentence-transformer model unless `--no-fine-tune` is set.
3. Compute and store face embeddings in `card_face_semantic_embeddings` unless `--no-embeddings` is set.
4. Export ONNX artifacts for API inference.
5. Update `data/semantic/runs/latest` to point at the newest run.

Useful commands:

```bash
# Full train + ONNX export + DB embeddings
uv run python -m ot_backend.embed.pipeline

# Use the base model without fine-tuning
uv run python -m ot_backend.embed.pipeline --no-fine-tune

# Recompute DB embeddings from the latest saved PyTorch model
uv run python -m ot_backend.embed.pipeline --reembed-only

# Load embeddings from a precomputed .npz file
uv run python -m ot_backend.embed.pipeline --load-embeddings path/to/embeddings.npz

# Export only the dataset
uv run python -m ot_backend.embed.pipeline --export-dataset data/training-dataset.json

# Evaluate the latest run against scripted queries
uv run python -m ot_backend.embed.pipeline --eval
```

Artifacts are stored under:

- `data/semantic/runs/<run-id>/config.json`
- `data/semantic/runs/<run-id>/metrics.json`
- `data/semantic/runs/<run-id>/training-dataset.json`
- `data/semantic/runs/<run-id>/models/pytorch/`
- `data/semantic/runs/<run-id>/models/onnx/`
- `data/semantic/runs/latest` -> latest successful run

## Environment variables

### Database and runtime

- `DATABASE_URL`: required in production; overrides `DB_*`
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`: local DB settings when `DATABASE_URL` is absent
- `ORACLE_TUTOR_API_ENV`: `development` or `production`
- `ORACLE_TUTOR_API_CORS_ORIGINS`: optional comma-separated allowlist
- `ORACLE_TUTOR_API_ALLOW_SCHEMA_RESET`: must be explicitly `true` to allow destructive schema reset flows
- `ORACLE_TUTOR_API_SCHEMA_WAIT_TIMEOUT_SECONDS`: API startup wait budget for schema readiness
- `ORACLE_TUTOR_API_SCHEMA_WAIT_INTERVAL_SECONDS`: polling interval while waiting for schema readiness

### Semantic model and caches

- `SEMANTIC_MODEL_PATH`: ONNX model directory used by the API; defaults to `data/semantic/runs/latest/models/onnx`
- `SEMANTIC_BASE_MODEL`: base Hugging Face model ID; defaults to `sentence-transformers/all-MiniLM-L6-v2`
- `SEMANTIC_RUNS_DIR`: optional override for semantic pipeline run output root
- `HF_HOME`: Hugging Face cache directory; defaults to `data/huggingface`

## Schema reset runbook

- API startup is non-destructive and waits for schema readiness.
- Destructive schema reset flows are guarded behind `ORACLE_TUTOR_API_ALLOW_SCHEMA_RESET=true`.
- For schema major/minor bumps:
  1. Temporarily enable `ORACLE_TUTOR_API_ALLOW_SCHEMA_RESET=true` on the ingestion worker.
  2. Run `scryfall-sync` once and confirm it completes successfully.
  3. Disable the reset flag again.
  4. Start or restart the API after migration state is `ready`.
- If migration state becomes `failed`, fix the worker/migration issue before repeatedly restarting the API.

## Docker

From the repo root:

```bash
docker compose up --build
```

That stack starts `db`, `api`, `frontend`, and the one-shot `scryfall-sync` service. If you want local app services without running ingestion immediately:

```bash
docker compose up --build db api frontend
```
