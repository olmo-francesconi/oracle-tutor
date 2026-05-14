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
- **Model registry** — read-only admin explorer for semantic models and datasets

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

This starts PostgreSQL (pgvector/pgvector:pg17), MinIO, the API (`:8000`), and the React frontend (`:5173`). The `ingest-worker` container is defined as a separate service and runs on a cron schedule.

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

Dataset generation, training, and promotion are run via local CLI scripts from `backend/scripts/`:

```bash
cd backend

# Build a dataset
uv run python scripts/build_dataset.py --output dataset.pkl --augmentation medium

# Train a fine-tuned model
uv run python scripts/train_model.py --dataset dataset.pkl --base-model "sentence-transformers/all-MiniLM-L6-v2" --output model.onnx

# Promote the model (materialize embeddings and activate)
uv run python scripts/promote_model.py --bundle model.onnx
```

For full details on the training workflow, see `RAILWAY.md`.

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
    ingest/                  Scryfall ingestion + parallel Tagger GraphQL sync
  scripts/                   Local CLI: build_dataset.py, train_model.py, promote_model.py
  tests/                     Pytest suite — real Postgres via testcontainers
  alembic/                   Initial schema + drop-semantic_jobs migration
frontend/
  src/
    public/                  SearchShell, HomeView, ResultsView + TanStack Query hooks
    admin/                   Admin explorer — ModelTable, DatasetTable, AdminPage + adminQueries
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
| GET | `/admin/semantic-models` | List all semantic models |
| GET | `/admin/semantic-models/{id}` | Get model detail |
| GET | `/admin/semantic-models/{id}/artifacts` | List model artifacts |
| GET | `/admin/semantic-datasets` | List all datasets |
| GET | `/admin/semantic-datasets/{id}` | Get dataset detail |
| GET | `/admin/semantic-datasets/{id}/artifacts` | List dataset artifacts |

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
semantic_datasets                        — training dataset records
  └── semantic_dataset_artifacts         — S3 artifact records per dataset
system_metadata / ingestion_logs         — operational tracking
```

The schema is defined by the ORM models in `backend/src/ot_backend/core/models.py`. The single migration `alembic/versions/0001_initial_schema.py` uses `Base.metadata.create_all()` plus explicit DDL for the pgvector HNSW index on `semantic_model_embeddings.embedding` and the GIN index on `card_faces.type_categories`.

## Railway deployment

The repo is designed to deploy as **four Railway services** plus Railway Postgres (with pgvector) and an S3-compatible bucket.

| Service | Dockerfile | Purpose |
|---|---|---|
| API | `backend/Dockerfile` | Web process |
| ingest-worker | `backend/Dockerfile.worker.ingest` | Daily scryfall-sync cron |
| Frontend | `frontend/Dockerfile` | nginx SPA + `/api` proxy |
| Database | Railway Postgres | pgvector-enabled database |


### Required environment variables

**All services:**
- `DATABASE_URL` — Railway Postgres connection string (injected automatically); Postgres must have pgvector
- `OT_ENV=production`

**API (runtime):**
- `ADMIN_PASSWORD` — password accepted by `POST /admin/auth/token`
- `ADMIN_JWT_SECRET` — HS256 signing secret for admin bearer tokens
- `CF_ACCESS_TEAM_DOMAIN` — Cloudflare Access team domain (e.g. `yourteam.cloudflareaccess.com`)
- `CF_ACCESS_AUD` — Cloudflare Access application AUD tag
- `SEMANTIC_ARTIFACT_ENDPOINT` — S3-compatible endpoint for model artifacts
- `SEMANTIC_ARTIFACT_ACCESS_KEY_ID` / `SEMANTIC_ARTIFACT_SECRET_ACCESS_KEY` — S3 credentials
- `SEMANTIC_ARTIFACT_BUCKET` — S3 bucket name

**Frontend:**
- `API_PROXY_TARGET` — internal URL of the API service
- `ADMIN_HOST` — hostname that serves the admin panel (e.g. `admin.oracletutor.org`); nginx returns 404 for `/admin/*` and `/api/admin/*` on any other host

### Admin panel security

The admin panel (model/dataset/job management) is gated by **two independent layers** in production:

1. **Host-based nginx routing.** The frontend nginx config only serves `/admin/*` and proxies `/api/admin/*` when the `Host` header matches `ADMIN_HOST`. On the public hostname these routes return 404 — no admin surface, no login form, nothing to probe.
2. **Cloudflare Access JWT verification.** Put the admin subdomain behind a [Cloudflare Access](https://www.cloudflare.com/zero-trust/products/access/) application that restricts login to your email. Every request Cloudflare forwards carries a `Cf-Access-Jwt-Assertion` header signed by your team; the FastAPI backend verifies it (RS256 against the Cloudflare JWKS, audience + issuer checks) on every `/admin/*` route, including `POST /admin/auth/token`.

In production (`OT_ENV=production` or any Railway env var present), if `CF_ACCESS_TEAM_DOMAIN` or `CF_ACCESS_AUD` is unset the backend **fails closed** — every admin request returns `503 "Cloudflare Access is not configured"`. Locally the check is skipped so `docker compose up` works with just `ADMIN_PASSWORD`.

Setup outline:

1. Point both `oracletutor.org` and `admin.oracletutor.org` at the same Railway frontend service (Cloudflare DNS, proxy enabled).
2. In Cloudflare Zero Trust → Access → Applications, create a self-hosted app on `admin.oracletutor.org` with an "Allow" policy limited to your email.
3. Copy the team domain (Settings → Custom Pages) and the application AUD tag (app → Overview) into the Railway API service env as `CF_ACCESS_TEAM_DOMAIN` and `CF_ACCESS_AUD`.
4. Set `ADMIN_HOST=admin.oracletutor.org` on the Railway frontend service.

### ingest-worker cron schedule

Set a **Railway Cron** on the `ingest-worker` service, e.g. `0 2 * * *` (daily at 02:00 UTC). The container runs the one-shot stale-aware worker once and exits.

## Attribution

Card data, images, and community tags come from [Scryfall](https://scryfall.com) under their [data terms](https://scryfall.com/docs/api). Oracle Tutor is an unofficial project and is not produced, endorsed, supported, or affiliated with Scryfall or Wizards of the Coast.

Magic: The Gathering is © Wizards of the Coast LLC. All card names, text, and imagery are property of their respective owners. No challenge to copyright is intended.

## License

[GNU General Public License v3.0](LICENSE)
