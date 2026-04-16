# Oracle Tutor

Fast semantic search for Magic: The Gathering cards — find cards by what they *do*, not just their name.

Built on pgvector embeddings with ONNX Runtime inference over Scryfall bulk data, serving a React SPA via a FastAPI backend.

## Features

- **Semantic search** — query by oracle text meaning ("deals damage to all creatures", "gains life when you draw") using sentence-transformer embeddings stored in pgvector
- **Similar cards** — find cards mechanically similar to any card in the database
- **Name autocomplete** — fast trigram-based name suggestions
- **Full card data** — 3-layer schema: raw Scryfall printings, oracle-deduplicated canonical cards, and per-face data with image URIs
- **Community tags** — Scryfall Tagger integration for semantic categories (shocklands, cantrips, etc.)
- **Daily sync** — Railway Cron `ingest-worker` pulls Scryfall bulk data and re-ingests changes automatically
- **Model registry** — admin panel for managing semantic models, datasets, and training/promotion jobs
- **Experiment tracking** — MLflow dual-write for model comparison and lineage

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12+, FastAPI, Hypercorn, SQLAlchemy 2 |
| Database | PostgreSQL with pgvector, Alembic migrations |
| Inference | ONNX Runtime (CPU), sentence-transformers (training only) |
| ML tracking | MLflow (experiment tracking, model registry) |
| Job queue | RQ + Redis |
| Ingestion | ijson streaming, Scryfall bulk API, Tagger GraphQL |
| Frontend | React 19, TypeScript, Vite 7, TailwindCSS 4, Framer Motion |
| Infra | Docker Compose (local), Railway (production), GitHub Actions (CI) |

## Local development

### Prerequisites
- Docker + Docker Compose
- `uv` (`brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node 20+ (for frontend-only work)

### Start everything

```bash
docker compose up --build
```

This starts PostgreSQL, Redis, MLflow, MinIO, the API (`:8000`), and the React frontend (`:5173`).

If you want the app stack without kicking off ingestion, start only the long-running services:

```bash
docker compose up --build db redis mlflow minio minio-init api frontend
```

### Backend (without Docker)

```bash
cd backend
uv sync --all-extras --group dev    # first time only

uv run ruff check src/ --fix        # lint
uv run basedpyright src/            # type check (0 errors expected)
uv run pytest -x -q                 # tests
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
- diff-ingests `cards_raw`, `cards`, and `card_faces`
- computes card uniqueness scores
- refreshes community tags unless `--skip-tags` is set

Useful variants:

```bash
# Force a full refresh even if metadata says the DB is current
uv run python -m ot_backend.ingest.main --force --strict --trigger-type manual

# Refresh Tagger data for every card
uv run python -m ot_backend.ingest.main --refresh-tags --strict --trigger-type manual

# Load card data only, skip Tagger sync
uv run python -m ot_backend.ingest.main --skip-tags --strict --trigger-type manual
```

### Run the semantic pipeline locally

The pipeline CLI manages the full model lifecycle via subcommands:

```bash
cd backend

# Export training dataset
uv run python -m ot_backend.embed.pipeline export /tmp/dataset.json

# Full fine-tune + ONNX export + embeddings
uv run python -m ot_backend.embed.pipeline run --epochs 5

# Skip fine-tuning, embed from base model only
uv run python -m ot_backend.embed.pipeline run --no-fine-tune

# Register a trained model bundle in the registry
uv run python -m ot_backend.embed.pipeline register ./model.zip --model-slug v2

# Promote a registered model to serve live traffic
uv run python -m ot_backend.embed.pipeline promote <model-id>

# Evaluate a run against scripted queries
uv run python -m ot_backend.embed.pipeline eval --eval-run-dir data/semantic/runs/<run-id>

# Recompute embeddings from an explicit model source
uv run python -m ot_backend.embed.pipeline reembed --base-model ./my-model
```

Pipeline runs are tracked in MLflow (available at `http://localhost:5050` when running via Docker Compose).

## Project structure

```
backend/
  src/ot_backend/
    api/
      main.py                App setup, lifespan, middleware, meta routes
      routers/               admin.py, search.py, telemetry.py
      schemas.py             Pydantic response schemas
    core/                    Config, database, ORM models, logging
    embed/
      index.py               Runtime ONNX inference + pgvector search
      pipeline.py            CLI (subcommands: run, export, register, promote, eval, reembed)
      mlflow_bridge.py       MLflow client wrapper (optional)
      task_queue.py          RQ enqueue helpers
      tasks.py               RQ task callables
      model_registry.py      Model materialization, promotion
      uniqueness.py          Card uniqueness scoring
      artifacts.py           S3 artifact storage
    ingest/                  Scryfall ingestion + Tagger sync
  tests/                     Pytest suite (SQLite in-memory)
  alembic/                   DB migrations
frontend/
  src/
    public/                  SearchShell, HomeView, ResultsView
    admin/                   Admin panel components
    components/              Shared UI components
    lib/                     API client, filters, helpers
  nginx/                     Nginx config + proxy_params
docs/                        Architecture roadmap
```

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/version` | Schema + API version |
| GET | `/oracle-samples` | Random sample oracle text and keyword pool for the UI |
| GET | `/search?q=` | Name search with trigram similarity |
| GET | `/card/{oracle_id}` | Full card by oracle ID |
| GET | `/similar-cards?oracle_id=` | Similar cards to a known oracle ID |
| GET | `/similar-cards?q=` | Semantic free-text search with optional filters |
| POST | `/telemetry/client-error` | Client error reporting |
| POST | `/telemetry/analytics` | Frontend analytics events |
| POST | `/admin/auth/token` | Exchange admin password for bearer token |
| GET | `/admin/semantic-models` | List registered semantic models |
| POST | `/admin/semantic-models` | Register a new model (bundle zip body) |
| POST | `/admin/semantic-jobs/dataset` | Create a dataset build job |
| POST | `/admin/semantic-jobs/train` | Create a training job |
| POST | `/admin/semantic-jobs/promote` | Create a promotion job |

Filters on `/similar-cards`: `card_type`, `colors`, `cmc_min`, `cmc_max`, `format`, `rarity`, `color_feature`, `match_mode`

```bash
curl "http://localhost:8000/similar-cards?q=deals+3+damage+to+any+target&limit=10"
```

## Database schema

```
cards_raw              — 1:1 Scryfall bulk mirror, all printings, ~300k rows
  └── cards            — oracle-deduplicated, one row per card identity, ~30k rows
        ├── card_faces                   — (oracle_id, face_ix) composite PK
        ├── card_taggings                — Scryfall Tagger community tags
        └── card_relationships           — related-card graph (tokens, meld, combos)
tags / tag_ancestor_map                  — tag definitions + hierarchy
semantic_models                          — registered model versions
  ├── semantic_model_artifacts           — S3 artifact records per model
  ├── semantic_model_embeddings          — pgvector(384) per (model, face)
  └── semantic_jobs                      — job history (promote, train, dataset)
semantic_datasets                        — training dataset records
  └── semantic_dataset_artifacts         — S3 artifact records per dataset
system_metadata / ingestion_logs         — operational tracking
```

Migrations are managed with **Alembic** (`backend/alembic/`).

## Railway deployment

The repo is designed to deploy as **four Railway services** + Railway Postgres + Railway Redis.

| Service | Dockerfile | Purpose |
|---|---|---|
| API | `backend/Dockerfile` | Web process |
| ingest-worker | `backend/Dockerfile.ingest-worker` | Daily ingest cron |
| train-worker | `backend/Dockerfile.train-worker` | Dataset export + Modal orchestration + model registration |
| promotion-worker | `backend/Dockerfile.promotion-worker` | Embedding build + model activation |
| Frontend | `frontend/Dockerfile` | nginx SPA + `/api` proxy |

### Required environment variables

**API + workers:**
- `DATABASE_URL` — Railway Postgres connection string (injected automatically)
- `ORACLE_TUTOR_API_ENV=production`
- `REDIS_URL` — Railway Redis connection string
- `MLFLOW_TRACKING_URI` — MLflow server URL

**train-worker (Modal orchestration):**
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
