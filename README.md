# Oracle Tutor

Fast semantic search for Magic: The Gathering cards — find cards by what they *do*, not just their name.

Built on pgvector embeddings with ONNX Runtime inference over Scryfall bulk data, serving a React SPA via a FastAPI backend.

## Features

- **Semantic search** — query by oracle text meaning ("deals damage to all creatures", "gains life when you draw") using sentence-transformer embeddings stored in pgvector
- **Similar cards** — find cards mechanically similar to any card in the database
- **Name autocomplete** — fast trigram-based name suggestions
- **Full card data** — 3-layer schema: raw Scryfall printings, oracle-deduplicated canonical cards, and per-face data with image URIs
- **Community tags** — Scryfall Tagger integration for semantic categories (shocklands, cantrips, etc.)
- **Daily sync** — Railway Cron `scryfall-sync` pulls Scryfall bulk data and re-ingests changes automatically

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

This starts Postgres, the API (`:8000`), and the React frontend (`:5173`). Workers are one-shot — run them manually when needed.

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
npm run build
```

### Run scryfall-sync locally

```bash
# From backend/
uv run python -m ot_backend.ingest.main --strict --trigger-type manual
```

Downloads Scryfall bulk data, populates `cards_raw` (~300k rows), derives `cards` and `card_faces` (~30k oracle-unique cards).

### Run oracle-embed locally

```bash
# From backend/ — requires a GPU or patience
uv run python -m ot_backend.embed.pipeline
```

Trains/exports ONNX model and computes embeddings for all card faces.

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/version` | Schema + API version |
| GET | `/search?q=` | Name search with trigram similarity |
| GET | `/suggest-names?q=` | Fast name autocomplete |
| GET | `/search-oracle?q=` | Semantic oracle-text search |
| GET | `/card/{oracle_id}` | Full card by oracle ID |
| GET | `/similar-cards/{oracle_id}` | Semantically similar cards |

```bash
curl "http://localhost:8000/search-oracle?q=deals+3+damage+to+any+target&limit=10"
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

The repo is designed to deploy as **three Railway services** + Railway Postgres.

| Service | Dockerfile | Purpose |
|---|---|---|
| API | `backend/Dockerfile` | Web process |
| scryfall-sync | `backend/Dockerfile.scryfall-sync` | Daily ingest cron |
| Frontend | `frontend/Dockerfile` | nginx SPA + `/api` proxy |

`oracle-embed` (model training + embedding) is a plain Python CLI script — run locally or as a one-off Railway job, no dedicated Docker service.

### Required environment variables

**API + scryfall-sync:**
- `DATABASE_URL` — Railway Postgres connection string (injected automatically)
- `ORACLE_TUTOR_API_ENV=production`

**API (runtime inference):**
- `SEMANTIC_MODEL_PATH` — path to directory with `onnx/model.onnx` and tokenizer assets

**Frontend:**
- `API_PROXY_TARGET` — internal URL of the API service

### scryfall-sync cron schedule

Set a **Railway Cron** on the `scryfall-sync` service, e.g. `0 2 * * *` (daily at 02:00 UTC). It runs the stale-aware update once and exits.

## License

[GNU General Public License v3.0](LICENSE)
