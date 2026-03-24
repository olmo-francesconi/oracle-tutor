# Architecture: Oracle Tutor

## Overview
Oracle Tutor is a Magic: The Gathering search application with a FastAPI backend, a React SPA frontend, and PostgreSQL storage. It combines trigram-based card-name lookup with semantic Oracle-text search backed by pgvector embeddings and ONNX Runtime inference over Scryfall bulk data.

## Stack
- Language: Python 3.12+, TypeScript 5.9
- Framework: FastAPI + Hypercorn, React 19 + Vite 7
- Key dependencies: SQLAlchemy 2, psycopg 3, pgvector, requests, ijson, ONNX Runtime, transformers, sentence-transformers, TanStack Query, React Router 7, Axios, Framer Motion, TailwindCSS 4, react-helmet-async
- Test runner: Pytest (backend); frontend uses ESLint + TypeScript/Vite build checks, no committed UI test suite

## Project structure
```text
backend/
  src/ot_backend/
    api/                FastAPI app, routes, Pydantic response schemas
    core/               config, DB engine/session, ORM models, schema init, logging
    embed/              semantic training pipeline, ONNX export/inference, text prep
    ingest/             one-shot Scryfall + Tagger ingestion worker
  tests/                pytest suite against SQLite in-memory DB
  scripts/              local utility/profiling scripts
frontend/
  src/
    components/         reusable UI, overlays, filters, mobile chrome
    pages/              home/search detail routes
    lib/                small helpers (`cn`, SEO helpers)
  nginx/                production nginx config/template
.github/workflows/      backend test/build workflow and path-filtered CI builds
docker-compose.yml      local db + api + ingest worker + semantic worker + frontend
```

## Components
- `backend/src/ot_backend/api/main.py`: single FastAPI app. Lifespan bootstraps DB readiness and eagerly probes semantic model availability. Routes: `/`, `/health`, `/version`, `/search`, `/suggest-names`, `/card/{id}`, `/search-oracle`, `/similar-cards/{id}`.
- `backend/src/ot_backend/api/schemas.py`: response models for fuzzy matches and semantic results.
- `backend/src/ot_backend/core/database.py`: central SQLAlchemy engine/session setup. Uses `DATABASE_URL` when present, otherwise composes a local Postgres URL from `DB_*`; treats Railway env vars as production; uses `StaticPool` for in-memory SQLite tests.
- `backend/src/ot_backend/core/models.py`: ORM schema for cards, faces, semantic embeddings, tags, taggings, relationships, ingestion logs, and `system_metadata`. Semantic vectors are stored at face granularity with dimension 384. SQLite falls back to JSON for embeddings when pgvector is unavailable.
- `backend/src/ot_backend/core/db_init.py`: schema bootstrap and migration-state coordination. Uses **Alembic** (`backend/alembic/`) to apply `upgrade head` on startup; worker mode writes migration state to `system_metadata` and updates schema version after a successful run.
- `backend/src/ot_backend/core/config.py`: canonical paths for data/model artifacts plus schema versioning and semantic model path resolution.
- `backend/src/ot_backend/core/logging_config.py`: named logger setup for API/ingest/embed flows and a `log_performance` decorator used on endpoints.
- `backend/src/ot_backend/ingest/main.py`: cron-friendly worker entry point; runs one ingestion pass and exits.
- `backend/src/ot_backend/ingest/data_builder.py`: fetches Scryfall bulk metadata/file, filters unsupported records, streams all printings into `cards_raw` (~300k rows), selects the best printing per `oracle_id` and upserts into `cards`/`card_faces`, deletes stale oracle rows, computes uniqueness, and can trigger Tagger sync.
- `backend/src/ot_backend/ingest/fetch_tags.py`: calls `tagger.scryfall.com` GraphQL, upserts tags, direct taggings, ancestor edges, and card relationships.
- `backend/src/ot_backend/embed/pipeline.py`: offline semantic pipeline. Builds a training dataset from face text plus selected Tagger-derived positive pairs, optionally fine-tunes a sentence-transformer, exports ONNX artifacts, and computes/stores embeddings.
- `backend/src/ot_backend/embed/index.py`: runtime semantic index. Lazily loads tokenizer + ONNX model from local files, encodes queries, and performs pgvector cosine-distance queries with optional server-side filters.
- `frontend/src/main.tsx`: SPA bootstrap with `QueryClientProvider` and `HelmetProvider`.
- `frontend/src/App.tsx`: browser-router shell with routes for `/`, `/search`, `/card/:id`; search/card pages are lazy-loaded.
- `frontend/src/api.ts`: all HTTP access is centralized here via an Axios instance rooted at same-origin `/api`.
- `frontend/src/pages/OracleSearchPage.tsx`: query-string-driven semantic search page using `useInfiniteQuery`, overlay navigation, and filter state.
- `frontend/src/pages/CardPage.tsx`: card detail page plus paginated similar-card browsing; treats the current card as the first item in overlay navigation.
- `frontend/src/components/CardGrid.tsx`: primary results surface. Groups results into similarity bands, auto-loads additional pages until low-similarity groups unless the user explicitly expands them, and hosts the desktop filter bar.
- `frontend/src/components/FilterBar.tsx`: local UI model for filters (`FilterState`) including color mode, rarity, CMC, type, and format.

## Data flow
1. `docker compose` or Railway brings up Postgres plus the API; worker containers are separate one-shot processes.
2. API startup calls `init_db(mode="api")`, which creates tables/extensions/indexes if needed and checks a migration-state flag in `system_metadata`; data endpoints return `503` while schema migration is marked in progress.
3. The ingest worker runs `update_scryfall_data()`, which initializes the DB in worker mode (running any pending Alembic migrations), downloads Scryfall bulk data, filters out tokens/digital-only/theme-card records, upserts all printings into `cards_raw`, derives oracle-unique `cards` and `card_faces`.
4. The same ingest flow can call Tagger sync, storing `tags`, `card_taggings`, `tag_ancestor_map`, and `card_relationships`.
5. The semantic worker runs `python -m ot_backend.embed.pipeline`, which derives training pairs from card faces and selected Tagger links, exports ONNX artifacts under `backend/data/semantic/runs/...`, and writes embeddings into `card_face_semantic_embeddings`.
6. Runtime semantic endpoints call `get_semantic_index()`, which loads tokenizer/model files from `SEMANTIC_MODEL_PATH` on first use and queries pgvector in Postgres for nearest faces.
7. `/search` and `/suggest-names` are still name-search endpoints: Postgres uses trigram similarity plus `ILIKE`; SQLite tests use the fallback `ILIKE` path only.
8. The frontend talks only to `/api`; Vite proxies `/api` to the backend in local dev, and nginx serves the built SPA with same-origin API proxying in production.

## Key conventions
- Backend uses a Python `src/` layout rooted at `backend/src/ot_backend`; tests manually add `backend/src` to `sys.path` instead of relying on editable installs.
- The backend has three dependency shapes in `backend/pyproject.toml`: `api`, `worker`, and `semantic-worker`; Dockerfiles install only the extra each image needs.
- Database schema is managed by **Alembic** (`backend/alembic/`). `init_db()` runs `alembic upgrade head` on every startup — safe for both API (no-op when current) and worker (applies pending migrations).
- The data model is 3-layer: `cards_raw` (all Scryfall printings, ~300k) → `cards` (oracle-deduplicated, ~30k, PK = `oracle_id`) → `card_faces` (composite PK `(oracle_id, face_ix)`).
- Semantic search is face-centric. Query vectors target `CardFaceSemanticEmbedding(oracle_id, face_ix)`, then results are hydrated back through `CardFace → Card`.
- Semantic artifacts are expected to be local files, not remote model pulls at request time. Runtime inference uses CPU ONNX only.
- Frontend server state uses TanStack Query; routing state lives in React Router params/query string; transient UI state stays in component state.
- Frontend network calls should go through `frontend/src/api.ts`; UI components do not fetch directly.
- Frontend filters are richer than the backend contract: the UI sends `match_mode`, but current semantic endpoints do not accept or apply it. `color_feature`, rarity, CMC, type, format, and color filters are implemented server-side in `embed/index.py`.
- The current API surface is hybrid: fuzzy/name endpoints still exist even though the roadmap/TODO describe an ongoing semantic-only migration.

## How to run
- Dev: `docker compose up --build`
- Backend setup: `cd backend && uv sync --all-extras --group test`
- Backend checks: `cd backend && uv run ruff check src/ --fix`, then `uv run basedpyright`, then `uv run pytest tests/ -x -q`
- Backend CI parity: `cd backend && uv sync --frozen --group test && uv run pytest`
- Frontend setup: `cd frontend && npm install`
- Frontend dev: `cd frontend && npm run dev`
- Frontend checks: `cd frontend && npm run lint && npm run build`
- Semantic worker: `cd backend && python -m ot_backend.embed.pipeline`
- Ingest worker: `cd backend && python -m ot_backend.ingest.main --strict --trigger-type cron`

## Key decisions
- Postgres is the system of record for both relational card data and semantic vectors; request handlers do not maintain a separate in-memory search index.
- Heavy work stays off the request path: Scryfall ingestion, Tagger sync, semantic training, ONNX export, and embedding recomputation are all batch jobs.
- Runtime inference uses locally stored ONNX artifacts plus `transformers` tokenization so the API image can serve semantic search without shipping sentence-transformers training dependencies.
- API and workers share the same ORM models and DB bootstrap code so ingestion/search stay aligned on schema assumptions.
- The frontend is a thin SPA over a same-origin HTTP API, which keeps deployment simple and avoids normal CORS requirements.
- The codebase favors direct modules over deep service layers; most behavior is concentrated in a small set of large files (`api/main.py`, `ingest/data_builder.py`, `embed/pipeline.py`, `pages/CardPage.tsx`, `components/CardGrid.tsx`).

## Critical constraints
- `DATABASE_URL` is required in production. Local development can fall back to `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`; `DB_PASSWORD` is mandatory when `DATABASE_URL` is absent.
- `SEMANTIC_MODEL_PATH` must point to a directory containing `onnx/model.onnx` (or legacy `model.onnx`) plus tokenizer assets. If the artifact is missing, semantic endpoints return `503`.
- Backend tests run against in-memory SQLite, so Postgres-only behavior such as pgvector distance queries, trigram operators, JSONB containment, and extension/index DDL is only partially covered in automated tests.
- Alembic migrations are applied automatically on startup. Never run destructive migrations in production without reviewing the migration file first.
- The repo may contain unrelated in-progress changes on feature branches. For architecture updates, treat the checked-in source as canonical unless a worktree diff clearly reflects an already-adopted structural change.
- Backend and frontend are versioned independently: `backend/pyproject.toml` is `2.0.0`, `frontend/package.json` is `1.4.0`.

## Last updated
2026-03-24
