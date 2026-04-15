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

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12+, FastAPI, Hypercorn, SQLAlchemy 2 |
| Database | PostgreSQL with pgvector, Alembic migrations |
| Inference | ONNX Runtime (CPU), sentence-transformers (training only) |
| Ingestion | ijson streaming, Scryfall bulk API, Tagger GraphQL |
| Frontend | React 19, TypeScript, Vite 7, TailwindCSS 4, TanStack Query |
| Infra | Docker Compose (local), Railway (production) |

## Local development

### Prerequisites
- Docker + Docker Compose
- `uv` (`brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node 20+ (for frontend-only work)

### Start everything

```bash
docker compose up --build
```

This starts Postgres, the API (`:8000`), the React frontend (`:5173`), and the one-shot `ingest-worker`.

If you want the app stack without kicking off ingestion, start only the long-running services:

```bash
docker compose up --build db api frontend
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

The previous SPA is preserved in `frontend-legacy/` as a rollback snapshot. It is no longer wired into Docker, CI, or deployment.

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

```bash
# From backend/ — requires the `oracle-embed` dependencies and some patience
uv run python -m ot_backend.embed.pipeline
```

The semantic pipeline can:
- build a training dataset from normalized oracle text plus community tags
- fine-tune a sentence-transformer model
- export ONNX artifacts for API inference
- compute and store face embeddings in Postgres

By default, runs are written under `backend/data/semantic/runs/<run-id>/`, and the latest successful run is linked at `backend/data/semantic/runs/latest/`. The API defaults `SEMANTIC_MODEL_PATH` to `data/semantic/runs/latest/models/onnx`.

Common workflows:

```bash
# Full fine-tune + ONNX export + DB embeddings
uv run python -m ot_backend.embed.pipeline

# Skip fine-tuning and embed from the base model only
uv run python -m ot_backend.embed.pipeline --no-fine-tune

# Recompute DB embeddings from the latest saved PyTorch model
uv run python -m ot_backend.embed.pipeline --reembed-only

# Export the training dataset without training
uv run python -m ot_backend.embed.pipeline --export-dataset data/training-dataset.json

# Evaluate the latest run against scripted queries
uv run python -m ot_backend.embed.pipeline --eval
```

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/version` | Schema + API version |
| GET | `/oracle-samples` | Random sample oracle text and keyword pool used by the UI |
| GET | `/search?q=` | Name search with trigram similarity |
| GET | `/card/{oracle_id}` | Full card by oracle ID |
| GET | `/similar-cards?oracle_id=` | Similar cards to a known oracle ID |
| GET | `/similar-cards?q=` | Semantic free-text search with optional filters |
| POST | `/admin/auth/token` | Exchange the configured admin password for an admin bearer token |

```bash
curl "http://localhost:8000/similar-cards?q=deals+3+damage+to+any+target&limit=10"
```

## Database schema

```
cards_raw          — 1:1 Scryfall bulk mirror, all printings, ~300k rows
  └── cards        — oracle-deduplicated, one row per card identity, ~30k rows
        └── card_faces          — (oracle_id, face_ix) composite PK, full face data
              └── card_face_semantic_embeddings   — pgvector(384) per face
        └── card_taggings       — Scryfall Tagger community tags
        └── card_relationships  — related-card graph (tokens, meld, combos)
tags / tag_ancestor_map         — tag definitions + hierarchy
```

Migrations are managed with **Alembic** (`backend/alembic/`).

## Railway deployment

The repo is designed to deploy as **four Railway services** + Railway Postgres.

| Service | Dockerfile | Purpose |
|---|---|---|
| API | `backend/Dockerfile` | Web process |
| ingest-worker | `backend/Dockerfile.ingest-worker` | Daily ingest cron |
| train-worker | `backend/Dockerfile.train-worker` | Railway-side dataset export + Modal orchestration + model registration |
| promotion-worker | `backend/Dockerfile.promotion-worker` | Railway-side embedding build + model activation |
| Frontend | `frontend/Dockerfile` | nginx SPA + `/api` proxy |

`oracle-embed` (dataset export, training, ONNX export, re-embedding, and eval) is a plain Python CLI workflow — run locally or as a one-off Railway job, no dedicated Docker service.

### Required environment variables

**API + ingest-worker + train-worker + promotion-worker:**
- `DATABASE_URL` — Railway Postgres connection string (injected automatically)
- `ORACLE_TUTOR_API_ENV=production`

**train-worker (Modal orchestration):**
- `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` — credentials used by the worker container to dispatch remote Modal jobs
- `SEMANTIC_LLM_MODEL` — optional Modal-side vLLM model ID; defaults to `Qwen/Qwen2.5-7B-Instruct`
- `SEMANTIC_LLM_MAX_QUERIES_PER_FACE` — optional cap for synthetic LLM queries per card face; defaults to `3`
- `SEMANTIC_LLM_MAX_FACES` — optional cap on how many faces receive LLM augmentation in one run; defaults to `2500`
- `SEMANTIC_LLM_MIN_TEMPLATE_COVERAGE` — only augment faces with fewer than this many template queries; defaults to `2`
- `SEMANTIC_LLM_TEMPERATURE` — optional vLLM sampling temperature; defaults to `0.6`
- `SEMANTIC_LLM_MAX_TOKENS` — optional max tokens per LLM response; defaults to `500`

**API (runtime inference):**
- `SEMANTIC_MODEL_PATH` — optional override for the ONNX model directory; defaults to `data/semantic/runs/latest/models/onnx`
- `SEMANTIC_BASE_MODEL` — optional Hugging Face base model ID for training and fallback model loading
- `ADMIN_PASSWORD` — password accepted by `POST /admin/auth/token`
- `ADMIN_JWT_SECRET` — HS256 signing secret for admin bearer tokens
- `ADMIN_LOGIN_MAX_FAILURES` — optional per-IP admin login failure threshold; defaults to `5`
- `ADMIN_LOGIN_LOCKOUT_SECONDS` — optional lockout period in seconds after hitting the threshold; defaults to `900`

**Frontend:**
- `API_PROXY_TARGET` — internal URL of the API service

### ingest-worker cron schedule

Set a **Railway Cron** on the `ingest-worker` service, e.g. `0 2 * * *` (daily at 02:00 UTC). The container command already runs the one-shot stale-aware worker once and exits.

## License

[GNU General Public License v3.0](LICENSE)
