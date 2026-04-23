# Oracle Tutor

Fast semantic search for Magic: The Gathering cards — find cards by what they *do*, not just their name.

Built on pgvector embeddings with ONNX Runtime inference over Scryfall bulk data, serving a React SPA via a FastAPI backend.

## Features

- **Semantic search** — query by oracle text meaning ("deals damage to all creatures", "gains life when you draw") using sentence-transformer embeddings stored in pgvector
- **Similar cards** — find cards mechanically similar to any card in the database
- **Name autocomplete** — fast card-name suggestions via TanStack Query debounced lookups
- **Full card data** — 3-layer schema: raw Scryfall printings, oracle-deduplicated canonical cards, and per-face data with image URIs
- **Community tags** — parallel Scryfall Tagger GraphQL integration for semantic categories (shocklands, cantrips, etc.)
- **Daily sync** — Railway Cron `ingest-worker` pulls Scryfall bulk data and re-ingests changes automatically
- **Model registry** — admin panel for managing semantic models, datasets, and training/promotion jobs

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12+, FastAPI, Hypercorn, SQLAlchemy 2, psycopg 3, uv |
| Database | PostgreSQL with pgvector, Alembic migrations |
| Inference | ONNX Runtime (CPU), sentence-transformers (training only) |
| Ingestion | ijson streaming, Scryfall bulk API, Tagger GraphQL |
| Artifact storage | S3-compatible (MinIO locally, any S3 in production) |
| Frontend | React 19, TypeScript, Vite 7, TailwindCSS 4, TanStack Query v5, zod |
| Infra | Docker Compose (local), Railway (production), GitHub Actions (CI) |

## Local development

### Prerequisites
- Docker + Docker Compose (required — tests spin up a Postgres container via testcontainers)
- `uv` (`brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node 20+ (for frontend-only work)

### Start everything

```bash
docker compose up --build
```

This starts PostgreSQL (pgvector/pgvector:pg17), MinIO, the API (`:8000`), and the React frontend (`:5173`). Worker containers (`ingest-worker`, `dataset-worker`, `train-worker`, `promotion-worker`) are defined as separate services and are invoked on demand.

If you want the app stack without kicking off ingestion, start only the long-running services:

```bash
docker compose up --build db minio minio-init api frontend
```

### Backend (without Docker)

```bash
cd backend
uv sync --all-extras --group dev    # first time only (includes testcontainers)

uv run ruff check src/ --fix        # lint
uv run basedpyright src/            # type check
uv run pytest -x -q                 # tests — requires Docker running; spawns a pgvector container
```

### Frontend (without Docker)

```bash
cd frontend
npm install          # first time only
npm run dev          # dev server at :5173 (proxies /api to backend)
npm run lint
npm run test
npm run build
```

### Run ingest-worker locally

```bash
# From backend/
uv run python -m ot_backend.ingest.main --strict --trigger-type manual
```

`ingest-worker` is a stale-aware one-shot worker. It compares remote Scryfall metadata, local bulk metadata, and DB metadata before deciding whether it needs to download and ingest anything.

When work is needed, it:
- downloads the latest Oracle Cards bulk file
- diff-ingests `cards_raw`, `cards`, and `card_faces` (including `type_categories` extracted from `type_line`)
- refreshes community tags in parallel (configurable via `TAG_FETCH_CONCURRENCY`) unless `--skip-tags` is set

Useful variants:

```bash
# Force a full refresh even if metadata says the DB is current
uv run python -m ot_backend.ingest.main --force --strict --trigger-type manual

# Refresh Tagger data for every card
uv run python -m ot_backend.ingest.main --refresh-tags --strict --trigger-type manual

# Load card data only, skip Tagger sync
uv run python -m ot_backend.ingest.main --skip-tags --strict --trigger-type manual
```

### Train and promote a semantic model

The model lifecycle runs through the admin panel + one-shot workers:

1. Open `http://localhost:5173/admin`, authenticate with `ADMIN_PASSWORD`.
2. **Queue dataset job** — picks augmentation mode, writes to `semantic_jobs`. The `dataset-worker` claims the job, builds the training dataset, uploads it as an artifact.
3. **Queue train job** — picks base model + hyperparameters + dataset. The `train-worker` claims the job, runs training (locally for smoke runs, or Modal for full fine-tunes), packages an ONNX bundle, registers it in `semantic_models`.
4. **Queue promote job** (or toggle "Queue promotion after register" on the train form) — the `promotion-worker` downloads the bundle, populates `semantic_model_embeddings`, flips `is_active`. The API picks up the new model on its next poll.

Workers can also be invoked directly for local testing:

```bash
uv run python -m ot_backend.semantic.dataset_worker --job-id <id>
uv run python -m ot_backend.semantic.train_worker --job-id <id>
uv run python -m ot_backend.semantic.promote_worker --job-id <id>
```

## Project structure

```
backend/
  src/ot_backend/
    api/
      main.py                App setup, lifespan (oracle pool rotation), middleware, meta routes
      oracle_pool.py         Homepage oracle-text / keyword pool loader + periodic rotation
      routers/               admin.py, search.py
      schemas.py             Pydantic response schemas
    core/                    Config, database, ORM models (source-of-truth schema), logging
    semantic/
      index.py               Runtime ONNX inference + pgvector search (HNSW-indexed)
      model_registry.py      Model CRUD, materialization, bundle utilities
      model_promotion.py     Single-entry `promote_semantic_model` orchestration
      artifacts.py           S3 artifact storage
      bundle_registration.py Bundle parsing and model registration
      dataset_worker.py      One-shot worker: build dataset, upload artifacts
      train_worker.py        One-shot worker: train (local or Modal), register bundle
      promote_worker.py      One-shot worker: materialize + embed + activate
      semantic_jobs.py       DB job records with FOR UPDATE SKIP LOCKED claim
    ingest/                  Scryfall ingestion + parallel Tagger GraphQL sync
  tests/                     Pytest suite — real Postgres via testcontainers
  alembic/                   Single initial-schema migration
frontend/
  src/
    public/                  SearchShell, HomeView, ResultsView + TanStack Query hooks
    admin/                   Admin panel — AdminPage, forms, tables, adminQueries/adminMutations
    components/              Shared UI + SearchBox autocomplete
    lib/                     API client (zod-validated), filters, URL state, queryClient
    types/                   TS types + zod schemas
  nginx/                     Nginx config + proxy_params
```

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/version` | Schema + API version |
| GET | `/oracle-samples` | Random sample oracle text and keyword pool for the UI |
| GET | `/search?q=` | Name search |
| GET | `/card/{oracle_id}` | Full card by oracle ID |
| GET | `/similar-cards?oracle_id=` | Similar cards to a known oracle ID |
| GET | `/similar-cards?q=` | Semantic free-text search with optional filters |
| POST | `/admin/auth/token` | Exchange admin password for bearer token (timing-safe compare) |
| GET/POST | `/admin/semantic-models` | List / register models |
| POST | `/admin/semantic-models/{id}/promote` | Queue a promote job |
| GET/POST | `/admin/semantic-datasets` | List datasets |
| GET | `/admin/semantic-base-models`, `/admin/semantic-train-options` | Training form metadata |
| GET | `/admin/semantic-jobs`, `/admin/semantic-jobs/{id}` | Jobs list + detail |
| POST | `/admin/semantic-jobs/{dataset,train,promote}` | Queue jobs |

Filters on `/similar-cards`: `card_type`, `colors`, `cmc_min`, `cmc_max`, `format`, `rarity`, `color_feature`, `match_mode`.

```bash
curl "http://localhost:8000/similar-cards?q=deals+3+damage+to+any+target&limit=10"
```

## Database schema

```
cards_raw              — 1:1 Scryfall bulk mirror, all printings, ~300k rows
  └── cards            — oracle-deduplicated, one row per card identity, ~30k rows
        ├── card_faces                   — (oracle_id, face_ix) composite PK
        │                                  + type_categories text[] with GIN index
        ├── card_taggings                — Scryfall Tagger community tags
        └── card_relationships           — related-card graph (tokens, meld, combos)
tags / tag_ancestor_map                  — tag definitions + hierarchy
semantic_models                          — registered model versions
  ├── semantic_model_artifacts           — S3 artifact records per model
  └── semantic_model_embeddings          — pgvector(384) per (model, face) + HNSW index
semantic_jobs                            — job history (dataset, train, promote)
semantic_datasets                        — training dataset records
  └── semantic_dataset_artifacts         — S3 artifact records per dataset
system_metadata / ingestion_logs         — operational tracking
```

The schema is defined by the ORM models in `backend/src/ot_backend/core/models.py`. The single `alembic/versions/0001_initial_schema.py` uses `Base.metadata.create_all()` plus explicit DDL for the pgvector HNSW index on `semantic_model_embeddings.embedding` and the GIN index on `card_faces.type_categories`.

## Railway deployment

The repo is designed to deploy as **five Railway services** plus Railway Postgres (with pgvector) and an S3-compatible bucket.

| Service | Dockerfile target | Purpose |
|---|---|---|
| API | `backend/Dockerfile` | Web process |
| ingest-worker | `backend/Dockerfile.worker` (`ingest` stage) | Daily scryfall-sync cron |
| dataset-worker | `backend/Dockerfile.worker` (`dataset` stage) | Build training datasets |
| train-worker | `backend/Dockerfile.worker` (`train` stage) | Train + Modal orchestration + register bundle |
| promotion-worker | `backend/Dockerfile.worker` (`promote` stage) | Embedding build + model activation |
| Frontend | `frontend/Dockerfile` | nginx SPA + `/api` proxy |

Workers set `ENV OT_SERVICE_ROLE=worker` which sizes their DB pool defaults to `2+1` (vs `10+5` on the API).

### Required environment variables

**API + workers:**
- `DATABASE_URL` — Railway Postgres connection string (injected automatically); Postgres must have pgvector
- `OT_ENV=production`

**train-worker + dataset-worker (Modal orchestration):**
- `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` — credentials for remote Modal jobs

**API (runtime):**
- `ADMIN_PASSWORD` — password accepted by `POST /admin/auth/token`
- `ADMIN_JWT_SECRET` — HS256 signing secret for admin bearer tokens
- `SEMANTIC_ARTIFACT_ENDPOINT` — S3-compatible endpoint for model artifacts
- `SEMANTIC_ARTIFACT_ACCESS_KEY_ID` / `SEMANTIC_ARTIFACT_SECRET_ACCESS_KEY` — S3 credentials
- `SEMANTIC_ARTIFACT_BUCKET` — S3 bucket name

**Frontend:**
- `API_PROXY_TARGET` — internal URL of the API service

### ingest-worker cron schedule

Set a **Railway Cron** on the `ingest-worker` service, e.g. `0 2 * * *` (daily at 02:00 UTC). The container runs the one-shot stale-aware worker once and exits.

## License

[GNU General Public License v3.0](LICENSE)
