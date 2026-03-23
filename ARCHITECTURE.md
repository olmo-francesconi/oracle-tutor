# Architecture: Oracle Tutor

## Overview
Oracle Tutor is a four-service system for Magic: The Gathering card search. A one-shot ingestion worker loads Scryfall data into PostgreSQL, a semantic worker materializes embeddings and the local inference model assets, the FastAPI service serves card lookup and semantic search over pgvector, and the React SPA consumes the API without route-specific frontend branching.

## Stack
- Language: Python 3.12+, TypeScript 5.9
- Framework: FastAPI + Hypercorn, React 19 + Vite
- Key dependencies: SQLAlchemy 2, PostgreSQL 17 + pgvector, sentence-transformers, psycopg 3, TanStack Query, Framer Motion, TailwindCSS 4
- Test runner: Pytest (API), frontend build validation via Vite/npm

## Project structure
```text
api/
  src/oracle_tutor_api/
    api/                HTTP routes, schemas, app bootstrap
    core/               config, DB session, models, init, logging
    semantic/           query encoding, pgvector search, text prep
    worker/             Scryfall ingestion and embedding build jobs
  tests/                API and integration-oriented tests
  Dockerfile            API image
  Dockerfile.worker     Scryfall ingestion worker image
  Dockerfile.semantic-worker
frontend/
  src/                  SPA pages, components, API client
  Dockerfile            frontend image / dev target
.github/workflows/      CI pipelines
docker-compose.yml      local db + api + worker + semantic-worker + frontend
docker-compose.prod.yml production-oriented compose overrides
```

## Components
- `api/src/oracle_tutor_api/api/main.py`: application bootstrap, lifespan, CORS, core REST routes, and the canonical `/search-oracle` and `/similar-cards/{id}` endpoints after semantic routing is folded into the main API.
- `api/src/oracle_tutor_api/semantic/index.py`: semantic search facade; lazy-loads a `SentenceTransformer` model from `data/semantic/model`, encodes query text, and executes pgvector cosine-distance queries.
- `api/src/oracle_tutor_api/semantic/text_prep.py`: normalizes Oracle text before embedding so query inference and offline card embedding generation stay aligned.
- `api/src/oracle_tutor_api/core/models.py`: SQLAlchemy models for cards, faces, legalities, and semantic embedding rows; pgvector-backed embeddings are stored per card face.
- `api/src/oracle_tutor_api/worker/data_builder.py`: one-shot ingestion worker that downloads Scryfall bulk data, upserts cards/faces, and exits without calling back into the API.
- `api/Dockerfile.semantic-worker`: dedicated batch worker environment for embedding generation and model preparation; keeps heavyweight semantic build tasks outside the API request path.
- `frontend/src`: SPA that continues to call `/search-oracle` and `/similar-cards/{id}`; the migration is backend-only from the client’s perspective.
- `docker-compose.yml`: local orchestration for Postgres, API, ingestion worker, semantic worker, and frontend dev server.

## Data flow
1. The ingestion worker downloads Scryfall bulk data, transforms it into relational card/card-face records, and upserts those rows into PostgreSQL.
2. The semantic worker generates or refreshes card-face embeddings and ensures inference assets exist at `data/semantic/model`.
3. The API starts, waits for schema readiness, and serves requests without building any in-memory search index at startup.
4. On the first semantic request, `get_semantic_index()` lazily loads the sentence-transformer model from disk into the API process.
5. `GET /search-oracle` normalizes the query text, encodes it into an embedding, and executes a pgvector cosine-distance query against stored face embeddings.
6. `GET /similar-cards/{id}` resolves the requested card to its primary face, uses that stored embedding as the query vector, excludes the seed face, and returns nearest neighbors.
7. Semantic search applies SQL-level filter parity during the pgvector query: `card_type`, `colors`, `color_feature`, `cmc_min`, `cmc_max`, `format`, and `rarity`.
8. The API hydrates matching `CardFace` and parent `Card` records into response models, and the frontend renders results via the existing `/api` proxy path.

## Key conventions
- Public search URLs stay stable: `/search-oracle` and `/similar-cards/{id}` remain the frontend contract.
- Semantic search is the only oracle-text search backend; there is no fallback ranking path.
- Embeddings are stored per card face, not per card, because Oracle text and face-level characteristics drive similarity.
- Query embeddings are computed online; corpus embeddings are computed offline.
- The semantic model is loaded lazily from `data/semantic/model` so API boot stays lightweight and failures are isolated to semantic requests.
- Search filters belong in the database query layer, not in post-processing, to preserve pagination and ranking correctness.
- Workers are one-shot jobs; they do their batch work and exit.

## How to run
- Dev: `docker compose up --build`
- API checks: `cd api && uv run ruff check src/ --fix && uv run basedpyright && uv run pytest tests/ -x -q`
- Frontend: `cd frontend && npm run build`
- Build: `docker compose build`

## Key decisions
- pgvector is the single search backend so ranking logic lives in the database and the API avoids maintaining a second in-memory index.
- Semantic inference stays in the API process for request-time query encoding, but expensive corpus embedding generation is pushed to a dedicated batch worker.
- Search remains face-centric because split cards, MDFCs, and similar layouts have face-specific Oracle text and gameplay semantics.
- The frontend API contract is preserved to make the migration operationally small and to avoid coupling UI rollout to backend internals.
- Model assets are loaded from the shared data volume rather than fetched on demand in production request paths.
- Filter parity is implemented in SQL alongside vector distance ordering so semantic search can replace legacy search without losing user-visible controls.

## Critical constraints
- `SentenceTransformer` inference requires model assets at `data/semantic/model`; if absent, semantic endpoints must fail explicitly rather than degrade silently.
- `CardFaceSemanticEmbedding` and related pgvector schema must exist before semantic endpoints are considered healthy.
- The API lifespan should remain limited to DB initialization and schema readiness; no startup-time embedding rebuilds or bulk index construction.
- Do not reintroduce worker-to-API rebuild callbacks, background search state, or alternative ranking modes.
- Route behavior must preserve pagination and response schema compatibility because the frontend is not changing paths for this migration.
- Versioning must stay aligned between `api/pyproject.toml` and `frontend/package.json`.

## Last updated
2026-03-23
