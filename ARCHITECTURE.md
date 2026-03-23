# Architecture: Oracle Tutor

## Overview
Oracle Tutor is a Magic: The Gathering card search application with a FastAPI backend, a React SPA frontend, and PostgreSQL storage. The current backend serves fuzzy card-name lookup from Postgres trigram search plus semantic Oracle-text search backed by pgvector embeddings and sentence-transformers.

## Stack
- Language: Python 3.12+, TypeScript 5.9
- Framework: FastAPI + Hypercorn, React 19 + Vite 7
- Key dependencies: SQLAlchemy 2, psycopg 3, pgvector, sentence-transformers, requests, ijson, TanStack Query, React Router 7, Axios, Framer Motion, TailwindCSS 4
- Test runner: Pytest for backend; frontend has lint/build checks but no committed test suite

## Project structure
```text
backend/
  src/ot_backend/
    api/                FastAPI app, route handlers, response schemas
    core/               config, DB engine/session, schema init, ORM models, logging
    embed/              model training, embedding computation, runtime semantic search
    ingest/             one-shot Scryfall ingestion and Tagger sync
  tests/                backend pytest suite (SQLite in-memory)
  scripts/              local profiling / stress scripts
  Dockerfile*           API, ingestion worker, semantic worker images
frontend/
  src/
    components/         reusable UI pieces, filters, overlays, grids
    pages/              routed screens (`/`, `/search`, `/card/:id`)
    lib/                small frontend helpers
  nginx/                runtime nginx config/template
  Dockerfile            Vite dev image + nginx runtime image
.github/workflows/      API CI, frontend CI, worker/frontend docker builds
docker-compose*.yml     local, prod, and worker-only compose definitions
```

## Components
- `backend/src/ot_backend/api/main.py`: single FastAPI app with lifespan-driven DB init and routes for `/search`, `/suggest-names`, `/card/{id}`, `/search-oracle`, `/similar-cards/{id}`, `/health`, `/version`.
- `backend/src/ot_backend/api/schemas.py`: Pydantic response models; `SimilarCard` is the shared payload for semantic search and similarity results.
- `backend/src/ot_backend/core/database.py`: builds SQLAlchemy engine from `DATABASE_URL` or local `DB_*` vars, treats Railway as production, uses `StaticPool` for in-memory SQLite tests.
- `backend/src/ot_backend/core/db_init.py`: owns schema bootstrap, Postgres extension/index creation, migration-state coordination via `system_metadata`, and destructive reset gating for ingest mode.
- `backend/src/ot_backend/core/models.py`: ORM schema for cards, faces, ingestion logs, tags, relationships, and `card_face_semantic_embeddings`; embeddings are face-level with dimension 384.
- `backend/src/ot_backend/ingest/main.py`: cron-friendly one-shot entry point; runs ingestion once and exits.
- `backend/src/ot_backend/ingest/data_builder.py`: downloads Scryfall bulk data, filters non-playable/digital-only records, chooses a preferred printing per `oracle_id`, upserts cards/faces, cleans stale rows, and optionally triggers tag sync.
- `backend/src/ot_backend/ingest/fetch_tags.py`: pulls GraphQL data from `tagger.scryfall.com` and stores tags, ancestor links, and card relationships.
- `backend/src/ot_backend/embed/train.py`: trains a sentence-transformer model from self-pairs plus tag-derived positive pairs and saves it to `data/embed/model`.
- `backend/src/ot_backend/embed/compute.py`: recomputes all face embeddings offline and stores them in Postgres.
- `backend/src/ot_backend/embed/index.py`: lazy-loads the trained model at runtime and executes pgvector cosine-distance queries.
- `frontend/src/api.ts`: Axios wrapper around same-origin `/api`; all frontend data access is centralized here.
- `frontend/src/App.tsx`: browser-router shell with lazy-loaded `CardPage` and `OracleSearchPage`.
- `frontend/src/pages/CardPage.tsx`: fetches one card plus paginated similar cards; manages overlay navigation and mobile details drawer.
- `frontend/src/pages/OracleSearchPage.tsx`: fetches paginated semantic search results from query-string state.
- `frontend/src/components/CardGrid.tsx`: main results surface; groups cards by similarity bands and handles incremental loading UX.
- `frontend/src/components/FilterBar.tsx`: shared filter UI; emits `FilterState` used in both card similarity and Oracle search flows.

## Data flow
1. The ingestion worker initializes schema in ingest mode, acquiring a Postgres advisory lock and marking migration state in `system_metadata`.
2. `ingest/data_builder.py` fetches Scryfall bulk metadata and the default-cards file, filters out unsupported records, reduces multiple printings to one preferred printing per `oracle_id`, and upserts `cards` plus `card_faces`.
3. The same worker can enrich cards with Scryfall Tagger data, populating `tags`, `card_taggings`, `tag_ancestor_map`, and `card_relationships`.
4. Semantic model training and embedding computation are offline jobs. Training writes model assets to `backend/data/embed/model`; compute writes vectors to `card_face_semantic_embeddings`.
5. API startup calls `init_db(mode="api")`, ensures extensions/tables/indexes exist, and waits for schema readiness before serving data endpoints.
6. `/search` and `/suggest-names` use Postgres trigram operators when available, with SQLite fallbacks for tests.
7. `/search-oracle` and `/similar-cards/{id}` call `get_semantic_index()`, which lazy-loads the sentence-transformer model from disk on first use, then queries pgvector for nearest neighbors.
8. The frontend talks only to `/api` through Vite dev proxy locally and nginx reverse proxy in production, then renders infinite-scroll result sets with React Query caching.

## Key conventions
- Python code uses a `src/` layout rooted at `backend/src/ot_backend`; tests add that path manually instead of relying on editable installs.
- Database schema is owned directly in SQLAlchemy models plus `core/db_init.py`; there is no Alembic migration layer.
- `init_db()` has two modes: API mode must never perform destructive resets, ingest mode may reset card tables only when `ORACLE_TUTOR_API_ALLOW_SCHEMA_RESET=true`.
- Schema readiness is coordinated through `system_metadata` rows rather than external migration tooling.
- Semantic search is face-centric: embeddings, similarity queries, and semantic ranking operate on `CardFace`, not whole-card aggregates.
- Semantic assets live under `backend/data/embed/model`; request-time inference assumes those files already exist.
- Frontend server state is handled with TanStack Query; route state lives in React Router query params/path params; local UI state stays in component state.
- Frontend requests are centralized in `frontend/src/api.ts`; component code should not hand-roll fetch calls.
- Filters are modeled in the frontend as `FilterState`, but the current backend semantic endpoints ignore the filter arguments they accept in the route signature and do not accept `match_mode` at all. The UI sends more filter state than the backend currently applies.
- Versioning is intentionally mirrored: `backend/pyproject.toml` and `frontend/package.json` are both `1.4.0`.

## How to run
- Dev: `docker compose up --build`
- Backend setup: `cd backend && uv sync --all-extras --group test`
- Backend checks: `cd backend && uv run ruff check src/ --fix && uv run basedpyright && uv run pytest tests/ -x -q`
- Frontend dev: `cd frontend && npm run dev`
- Frontend checks: `cd frontend && npm run lint && npm run build`
- Build: `docker compose build`

## Key decisions
- Postgres is the system of record for both relational card data and semantic vectors; the API does not maintain a separate in-memory search index.
- Fuzzy name search and semantic Oracle-text search currently coexist: trigram search covers name lookup, pgvector covers meaning-based retrieval.
- Heavy operations are pushed out of the request path: ingestion, model training, and embedding recomputation are batch jobs.
- The API and worker share ORM models and DB-init logic to keep schema assumptions aligned.
- The frontend is a thin SPA over a stable HTTP contract and uses same-origin `/api` proxying to avoid CORS complexity in normal deployments.
- The codebase prefers direct, explicit modules over deep abstraction layers; most behavior is concentrated in a few large files (`backend/src/ot_backend/api/main.py`, `backend/src/ot_backend/ingest/data_builder.py`, `frontend/src/components/CardGrid.tsx`, `frontend/src/components/FilterBar.tsx`).

## Critical constraints
- `DATABASE_URL` is mandatory in production; local development instead uses `DB_*` vars from compose.
- `DB_PASSWORD` must be set for non-`DATABASE_URL` local runs; the backend will refuse to start without it.
- `sentence-transformers` model files must exist at `SEMANTIC_MODEL_PATH` for semantic endpoints to work; otherwise `/search-oracle` and `/similar-cards/{id}` return 503.
- Backend tests run against in-memory SQLite, so Postgres-only behavior such as pgvector distance queries and trigram operators is only partially covered in automated tests.
- CI is split: `.github/workflows/api-ci.yml` runs backend tests and API image build, while `.github/workflows/ci.yml` conditionally builds frontend assets/images and worker image based on changed paths.
- Planned rename work appears in `.agent-config/PINBOARD.md`, but the checked-in code still uses `ot_backend`, `ingest`, and `embed`.

## Last updated
2026-03-23
