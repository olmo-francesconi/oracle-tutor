# Oracle Tutor (mtg-search)

Fast, semantic search engine for Magic: The Gathering cards — pgvector embeddings with ONNX Runtime inference over Scryfall bulk data, serving a React SPA via a FastAPI backend.

## Tech stack

- **Backend:** Python 3.12+, FastAPI 0.115+, Hypercorn 0.17+, SQLAlchemy 2, psycopg 3.2+, pgvector 0.3+, ONNX Runtime 1.20+, Alembic 1.14+, sentence-transformers 3.0+ (training only), uv
- **Frontend:** React 19.2, TypeScript 5.9, Vite 7.2, TailwindCSS 4.1, TanStack Query v5, zod
- **Infra:** Docker Compose (local), Railway (production), GitHub Actions (CI)

## Repo structure

```
backend/                FastAPI service + Pytest suite
  src/ot_backend/
    api/
      main.py           App setup, lifespan, middleware, meta routes
      oracle_pool.py    Homepage oracle-text/keyword pool loader + rotation
      routers/          admin.py, search.py
      schemas.py        Pydantic response schemas
    core/               Config, DB engine/session, schema init, ORM models, logging
    semantic/
      index.py          Runtime ONNX inference + pgvector search
      model_registry.py Model CRUD, materialization, bundle utilities
      model_promotion.py Model promotion (claim + embed + activate) entry point
      artifacts.py      S3 artifact upload/download
      bundle_registration.py Bundle parsing and model registration
      base_model_catalog.py  Base model listing and retrieval
      semantic_jobs.py  DB job records: create, list, succeed/fail
    ingest/             One-shot Scryfall ingestion (scryfall_ingestion.py), parallel Tagger sync (fetch_tags.py)
  tests/                Pytest suite (real Postgres via testcontainers + pgvector)
  alembic/              Single initial-schema migration (versions/0001_initial_schema.py)
  Dockerfile            API image
  Dockerfile.worker     Multi-target worker image (ingest, dataset, train, promote)
frontend/               React + Vite SPA
  src/
    public/             SearchShell, HomeView, ResultsView, useUrlSync
                         use{Oracle,Card,Search,Similar}Query (TanStack Query hooks)
    admin/              AdminPage, DatasetForm, TrainForm, ModelTable, DatasetTable, JobList
                         adminQueries.ts + adminMutations.ts
    components/         UI components (SearchBox + useCardAutocompleteQuery, overlays, shared presentation)
    lib/                api.ts (zod-validated), adminApi.ts, filters.ts, urlState.ts,
                         queryClient.ts (shared TanStack QueryClient), testQueryClient.tsx
    types/              api.ts (TS types), schemas.ts (zod schemas)
  nginx/                Nginx config + shared proxy_params snippet
  Dockerfile            Multi-stage build (Vite dev + nginx runtime)
.github/workflows/      ci.yml (frontend + workers), api-ci.yml (backend)
docker-compose.yml      Local dev: db + minio + api + frontend + worker targets
```

## Architecture

### Data model (3-layer)
- `cards_raw` — all Scryfall printings (~300k rows), PK = Scryfall UUID
- `cards` — oracle-deduplicated, PK = `oracle_id` (~30k rows)
- `card_faces` — composite PK `(oracle_id, face_ix)`; `type_categories text[]` with GIN index for fast card-type filtering

Additional tables: `tags`, `card_taggings`, `tag_ancestor_map`, `card_relationships`, `system_metadata`, `ingestion_logs`

Semantic model registry tables: `semantic_models`, `semantic_model_artifacts`, `semantic_model_embeddings`, `semantic_datasets`, `semantic_dataset_artifacts`, `semantic_jobs`

### Semantic search
- Embeddings stored per-model in `semantic_model_embeddings` (face granularity, filtered by `model_id`)
- pgvector HNSW index on `embedding` for fast cosine-distance lookups
- Query → ONNX tokenizer/model → pgvector cosine distance → hydrate via `CardFace → Card`
- Active model is determined by `semantic_models.is_active`; index polls DB every `SEMANTIC_ACTIVE_MODEL_POLL_SECONDS` seconds
- Model artifacts (ONNX bundle zip) stored in S3-compatible storage; materialized to `SEMANTIC_TEMP_DIR` on demand
- Semantic endpoints return 503 if no active model exists in the registry

### Job queue
- Admin routes create a DB job record, then dispatch to one-shot worker containers triggered on demand
- Workers (`promote_worker.py`, `dataset_worker.py`, `train_worker.py`) are one-shot containers on Railway
- `claim_next_semantic_job` uses `FOR UPDATE SKIP LOCKED` so concurrent workers don't thrash on the same row
- `promote_semantic_model` is the single end-to-end entry point (claim → embed → activate); replaced the prior begin/run two-step

### API routes
| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Root health check |
| `/health` | GET | `{"status": "ok"}` |
| `/version` | GET | `{"version": API_VERSION}` |
| `/oracle-samples` | GET | Random oracle text and keyword samples for the UI |
| `/search` | GET | Name-based card search (param: `q`) |
| `/card/{oracle_id}` | GET | Card detail with faces |
| `/similar-cards` | GET | Semantic search (params: `oracle_id` or `q`, `face_ix`, `limit`, `offset`, filters) |
| `/admin/auth/token` | POST | Exchange admin password for bearer token (timing-safe compare) |
| `/admin/semantic-models` | GET | List all registered semantic models |
| `/admin/semantic-models` | POST | Register a new semantic model (bundle zip body) |
| `/admin/semantic-models/{model_id}` | GET | Get semantic model detail |
| `/admin/semantic-models/{model_id}/artifacts` | GET | List model artifacts |
| `/admin/semantic-models/{model_id}/promote` | POST | Queue promotion job for a model |
| `/admin/semantic-jobs` | GET | List all semantic jobs |
| `/admin/semantic-jobs/{job_id}` | GET | Get job detail |
| `/admin/semantic-datasets` | GET | List all datasets |
| `/admin/semantic-datasets/{dataset_id}` | GET | Get dataset detail |
| `/admin/semantic-datasets/{dataset_id}/artifacts` | GET | List dataset artifacts |
| `/admin/semantic-base-models` | GET | List available base models |
| `/admin/semantic-train-options` | GET | Get training option schemas |
| `/admin/semantic-jobs/dataset` | POST | Create a dataset build job |
| `/admin/semantic-jobs/train` | POST | Create a training job |
| `/admin/semantic-jobs/promote` | POST | Create a promotion job |

Filters on `/similar-cards`: `card_type`, `colors`, `cmc_min`, `cmc_max`, `format`, `rarity`, `color_feature` (`"identity"` | `"colors"`), `match_mode` (`"at_least"` | `"at_most"` | `"exact"`). `card_type` filters via array overlap on the GIN-indexed `type_categories` column; `matchMode` / `colorFeature` / `rarities` are allowlist-validated in `lib/filters.ts` before hitting the URL.

### Key files
- `api/main.py` — FastAPI app setup, lifespan, middleware, meta routes; includes routers; spawns `rotate_oracle_pools` background task
- `api/oracle_pool.py` — `load_oracle_pools`, `rotate_oracle_pools` (homepage sample refresh every `OT_ORACLE_POOL_REFRESH_SECONDS`)
- `api/routers/admin.py` — all `/admin/*` routes + semantic model/job serializers
- `api/routers/search.py` — `/search`, `/card/{oracle_id}`, `/similar-cards`, `/oracle-samples`
- `core/models.py` — ORM models (source of truth for the schema); composite PKs for card_faces and embeddings; pgvector `Vector` type
- `core/db_init.py` — runs `alembic upgrade head` on every startup; session-level `pg_advisory_lock` held across Alembic; migration state FSM
- `ingest/scryfall_ingestion.py` — stale-aware Scryfall bulk ingest, card derivation, `type_categories` extraction from `type_line`; delete phase is a single transaction (no split-state on crash)
- `ingest/fetch_tags.py` — Scryfall Tagger GraphQL sync; `ThreadPoolExecutor` (default 6 workers) with per-thread sessions and a shared rate-limit semaphore
- `semantic/index.py` — runtime: lazy-loads ONNX model, encodes queries, pgvector cosine search with server-side filters
- `semantic/model_registry.py` — model CRUD, materialization, bundle utilities
- `semantic/model_promotion.py` — `promote_semantic_model` end-to-end orchestration; atomic single-txn embedding replacement
- `semantic/artifacts.py` — S3 artifact upload/download and recording
- `semantic/bundle_registration.py` — bundle parsing and model registration
- `semantic/base_model_catalog.py` — base model listing and retrieval
- `semantic/semantic_jobs.py` — DB job records; `FOR UPDATE SKIP LOCKED` on claim
- `semantic/semantic_state.py` — semantic data version tracking
- `frontend/src/lib/api.ts` — fetch client with `searchCards`, `getCard`, `getSimilarCards`, `searchOracleText`; every response parsed through a zod schema
- `frontend/src/lib/queryClient.ts` — shared `QueryClient` with a retry predicate that skips 4xx
- `frontend/src/types/schemas.ts` — zod schemas for every API response shape

### Frontend conventions
- Server state: TanStack Query v5 — `useQuery` / `useInfiniteQuery` hooks in `public/use*Query.ts` and `admin/adminQueries.ts`; writes via `useMutation` in `admin/adminMutations.ts`. Query keys prefixed `['admin', ...]` so the Refresh button can invalidate the whole admin board.
- URL state: custom `useUrlSync` hook driving `window.history` (no React Router). URL is the source of truth for `query` / `pinnedCard` / `filters`.
- Transient UI: component state.
- UI components do not fetch directly — use `src/lib/api.ts` / `src/lib/adminApi.ts`, which are wrapped by the query hooks.
- Filters (color, CMC, type, rarity, format) are applied server-side in `semantic/index.py`. `lib/filters.ts` allowlists enum values before they reach the URL.
- API responses are runtime-validated via zod; a malformed response throws `Malformed response: ...`.
- Admin 401 handling: `adminApi.ts` calls `setAdminUnauthorizedHandler` which `AdminApp` uses to flip `isAuthed` — no page reload.

## Operational notes

- `/search` is still name-based; semantic free-text search runs through `/similar-cards?q=...`
- API startup queries the registry for the active semantic model; returns `503` from semantic endpoints until one is promoted
- `ingest-worker` is a one-shot container; it can skip download/ingestion entirely when DB metadata already matches the latest Scryfall bulk timestamp
- Tagger refresh runs in parallel (configurable via `TAG_FETCH_CONCURRENCY`, default 6); per-thread sessions prevent one 429 from invalidating all workers
- Model bundles are stored in S3 (`SEMANTIC_ARTIFACT_BUCKET`) and cached locally in `SEMANTIC_TEMP_DIR`
- Homepage oracle/keyword pools are loaded at lifespan start and refreshed every `OT_ORACLE_POOL_REFRESH_SECONDS`

## Branch conventions

- `main` — production releases (protected)
- `develop` — active development, PRs merge here first
- `production` — alternative production channel
- Feature branches: `feat/<name>`, fixes: `fix/<name>`

## Git commits

- Use `type: message` commit subjects
- Allowed types: `feat`, `fix`, `docs`, `refactor`, `chore`, `test`
- Keep subjects imperative, concise, and without a trailing period
- Never add `Co-Authored-By` or any other trailer
- Example: `fix: handle empty oracle query`

## Environment variables

**Backend:**
| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | — | Required; Railway injects. Must point at a Postgres with pgvector. |
| `DB_USER` | `oracle` | Local Postgres user (used only when `DATABASE_URL` is absent) |
| `DB_PASSWORD` | — | Required when `DATABASE_URL` is absent |
| `DB_HOST` | `localhost` | |
| `DB_PORT` | `5432` | |
| `DB_NAME` | `mtg_search` | |
| `OT_SERVICE_ROLE` | `api` | `api` \| `worker` — sizes the DB pool defaults |
| `DB_POOL_SIZE` | `10` (api) / `2` (worker) | |
| `DB_POOL_MAX_OVERFLOW` | `5` (api) / `1` (worker) | |
| `DB_POOL_RECYCLE` | `3600` | |
| `DB_POOL_TIMEOUT` | `30` | |
| `OT_ENV` | `development` | `development` \| `production` |
| `OT_CORS_ORIGINS` | — | Comma-separated allowed origins |
| `SEMANTIC_ACTIVE_MODEL_POLL_SECONDS` | `5` | How often the API checks for a new active model |
| `OT_ORACLE_POOL_REFRESH_SECONDS` | `600` | How often the API rotates the homepage oracle-text/keyword pools |
| `SEMANTIC_TEMP_DIR` | `$TMPDIR/mtg-search-semantic-models` | Local cache for materialized model bundles |
| `SEMANTIC_ONNX_INTRA_OP_THREADS` | `1` | ONNX Runtime intra-op thread count |
| `SEMANTIC_ONNX_INTER_OP_THREADS` | `1` | ONNX Runtime inter-op thread count |
| `SEMANTIC_JOB_HEARTBEAT_SECONDS` | `600` | Promote worker heartbeat interval |
| `SEMANTIC_JOB_STALE_SECONDS` | `1200` | Seconds before a running job is considered stale |
| `TAG_FETCH_CONCURRENCY` | `6` | Parallel workers for Scryfall Tagger sync |
| `ADMIN_PASSWORD` | — | Required for admin routes |
| `ADMIN_JWT_SECRET` | — | HS256 signing secret for admin bearer tokens |
| `ADMIN_LOGIN_MAX_FAILURES` | `5` | Failed admin logins per IP before lockout |
| `ADMIN_LOGIN_LOCKOUT_SECONDS` | `900` | Lockout duration after hitting the failure threshold |
| `HF_HOME` | `data/huggingface` | Hugging Face cache directory |
| `OT_LOG_TO_FILES` | — | Enable file logging |
| `SEMANTIC_ARTIFACT_ENDPOINT` | — | S3-compatible endpoint URL for artifact storage |
| `SEMANTIC_ARTIFACT_ACCESS_KEY_ID` | — | S3 access key ID for artifact storage |
| `SEMANTIC_ARTIFACT_SECRET_ACCESS_KEY` | — | S3 secret access key for artifact storage |
| `SEMANTIC_ARTIFACT_REGION` | `auto` | S3 region for artifact storage |
| `SEMANTIC_ARTIFACT_BUCKET` | — | S3 bucket name for semantic model artifacts |

**Frontend:**
| Variable | Notes |
|---|---|
| `VITE_API_URL` | API base path (default `/api`) |
| `VITE_APP_URL` | App URL used for canonical SEO links |

## Dev workflows

### Local dev
```bash
docker compose up --build   # db + minio + api + frontend (+ worker targets on demand)
```

### Backend (run in `backend/`)
```bash
uv sync --all-extras --group dev    # once (includes testcontainers for tests)

uv run ruff check src/ --fix        # lint
uv run basedpyright src/            # type check
uv run pytest -x -q                 # tests — requires Docker running; session spins up pgvector container

# Run scryfall-sync manually:
uv run python -m ot_backend.ingest.main --strict --trigger-type manual

# Apply migrations standalone (requires DATABASE_URL set):
DATABASE_URL=postgresql+psycopg://... uv run alembic upgrade head
```

### Frontend (run in `frontend/`)
```bash
npm install        # once
npm run dev        # localhost:5173, proxies /api to backend
npm run lint
npm run test
npm run build
```

## Rules

- Backend versioned independently from frontend: `backend/pyproject.toml` = `2.0.0`, `frontend/package.json` = `2.0.0`
- Worker is a one-shot container; runs daily via Railway Cron and exits
- Never run destructive Alembic migrations in production without reviewing the migration file first
- Tests run against a real Postgres (via testcontainers + `pgvector/pgvector:pg17`). Docker must be running locally and in CI.
- `DATABASE_URL` is always required (production, local, and Alembic CLI). No sqlite fallback anywhere.
- Source of truth for the schema is the ORM models in `core/models.py`; the single `0001_initial_schema.py` migration uses `Base.metadata.create_all()` plus explicit DDL for the HNSW and GIN indexes.
- No dialect branching in app code — Postgres is the only supported database.
