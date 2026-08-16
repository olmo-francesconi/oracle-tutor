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
    ingest/             One-shot Scryfall ingestion (scryfall_ingestion.py), parallel Tagger sync (fetch_tags.py)
  scripts/              Local CLI tools: build_dataset.py, train_model.py, promote_model.py
  tests/                Pytest suite (real Postgres via testcontainers + pgvector)
  alembic/              Incremental migrations (0001_initial_schema.py .. 0007_ability_keyword_flag.py)
  Dockerfile            API image
  Dockerfile.worker.ingest     Ingest worker image (CMD baked: scryfall-sync cron)
frontend/               React + Vite SPA
  src/
    public/             SearchShell, HomeView, ResultsView, useUrlSync
                         use{Oracle,Card,Search,Similar}Query (TanStack Query hooks)
    admin/              AdminPage (2-tab read-only explorer), ModelTable, DatasetTable
                         adminQueries.ts (no mutations — admin is read-only)
    components/         UI components (SearchBox + useCardAutocompleteQuery, overlays, shared presentation)
    lib/                api.ts (zod-validated), adminApi.ts, filters.ts, urlState.ts,
                         queryClient.ts (shared TanStack QueryClient), testQueryClient.tsx
    types/              api.ts (TS types), schemas.ts (zod schemas)
  nginx/                Nginx config + shared proxy_params snippet
  Dockerfile            Multi-stage build (Vite dev + nginx runtime)
.github/workflows/      ci.yml (frontend + ingest worker), api-ci.yml (backend)
docker-compose.yml      Local dev: db + minio + api + frontend (+ ingest-worker on the `manual` profile)
```

## Architecture

### Data model (3-layer)
- `cards_raw` — the winning printing per oracle_id (~33.6k rows), PK = Scryfall UUID. Ingest reads the full `default-cards` bulk file (~117k printings) but only persists the printing `select_best_printing` picks, so this is NOT every printing
- `cards` — oracle-deduplicated, PK = `oracle_id` (~30k rows)
- `card_faces` — composite PK `(oracle_id, face_ix)`; `type_categories text[]` with GIN index for fast card-type filtering
- `card_face_abilities` — composite PK `(oracle_id, face_ix, ability_ix)`; one row per ability, segmented from oracle text at ingest time. `text_hash` is the dedup/join key onto embeddings; `is_keyword` flags bare keyword abilities (Flying, Ward {2}) — ~23% of rows

Additional tables: `tags`, `card_taggings`, `tag_ancestor_map`, `card_relationships`, `system_metadata`, `ingestion_logs`

Semantic model registry tables: `semantic_models`, `semantic_model_artifacts`, `semantic_ability_embeddings`, `semantic_datasets`, `semantic_dataset_artifacts`
(`semantic_model_embeddings` is the retired face-granular table — nothing reads it; migration 0007 will drop it)

### Semantic search
Similarity is computed over **abilities**, not whole cards. The layer chain is
`[card] → [card_face] → [oracle text] → [abilities]`.

- Oracle text is split into abilities by `semantic/ability_split.py` (newline-per-ability, with keyword lines like "Flying, vigilance, haste" or "First strike; banding" split on `,`/`;` via Scryfall's keyword-ability catalog; modal `•` lines stay attached to their parent ability)
- Embeddings stored per-model in `semantic_ability_embeddings`, keyed by `(model_id, text_hash)` — one vector per **distinct ability text**, so ~63k ability instances collapse to ~37k vectors and a kNN probe returns distinct abilities instead of N copies of "flying"
- No HNSW index: retrieval applies SQL filters alongside distance ordering, and pgvector's HNSW post-filters, which would silently cost recall. Exact cosine over ~37k rows is fast enough
- Retrieval is two-stage (`semantic/index.py`):
  1. **Candidate generation** — per-ability kNN (one probe per seed ability), filters applied, unioned into a candidate face set
  2. **Rerank** — bidirectional Chamfer mean over ability sets: `(mean_i max_j sim + mean_j max_i sim) / 2`. A card matching across all its abilities outranks one sharing a single keyword
- Both means are **IDF-weighted** by ability document frequency, so common text stops dominating. Weighting is by frequency rather than keyword-ness on purpose: the most common abilities include non-keywords (`Enchant creature` df=915, `{T}: Add {C}.` df=445) alongside `Flying` (df=3235). The df map is cached per index instance
- `is_keyword` is metadata, not a scoring filter: nothing in retrieval branches on it. It is returned by `/card/{oracle_id}` so the ability tuner can reject a face's keywords in one action, and IDF already de-emphasises them. The `ignore_keywords` / `noKw` filter that used to drop them from scoring was removed — ability tuning covers the same intent, and 502 keyword-only faces meant a blanket filter could empty a seed entirely
- **Text queries (`q`) use forward/max-pool only**, deliberately: someone searching "draw a card when a creature dies" wants cards with that ability and should not see them demoted for also having flying
- **Multi-ability queries**: ` // ` in `q` segments the query through `split_query_abilities`, which reuses `split_ability_lines`, so a query is segmented by exactly the same rules as the corpus (newlines, keyword `,`/`;` lists, modal bullets) — pasting real oracle text works as-is. Each ability becomes its own kNN probe and `forward` averages over them, giving AND semantics: `flying // whenever this creature attacks, draw a card` ranks Dream Trawler over Library Larcenist, which has the draw trigger but no flying and tied for first as a single blurred vector. Capped at `MAX_QUERY_ABILITIES` (6) — one exact scan of ~37k vectors each — and 422 beyond, never silently truncated. The seed side is deliberately NOT IDF-weighted here (unlike card mode): the user typed each ability on purpose. `/similar-cards` echoes the segmentation back as `query_abilities` so the UI need not ship a second copy of the splitter
- `//` was chosen over `;`, `|` and `&` on corpus evidence: across 63,254 ability rows it occurs 2 times (both card names, `SP//dr`) versus 60, 156 and 23
- `/similar-cards` returns `matched_ability` — the specific ability that drove each match. Chosen by relevance first (within `_DISPLAY_SIMILARITY_MARGIN` of the best match), then most-distinctive-by-IDF as tiebreak; a raw argmax reports "Flying" for every flier, a pure IDF argmax reports the most obscure ability instead
- Active model is determined by `semantic_models.is_active`; index polls DB every `SEMANTIC_ACTIVE_MODEL_POLL_SECONDS` seconds
- Model artifacts (ONNX bundle zip) stored in S3-compatible storage; materialized to `SEMANTIC_TEMP_DIR` on demand
- Semantic endpoints return 503 if no active model exists in the registry

### Semantic operations
- Dataset generation, training, and promotion are operator-run local CLI scripts in `backend/scripts/`
- Scripts call library functions (`promote_semantic_model`, `register_model_bundle_bytes`, etc.) and write directly to the model/dataset tables
- No DB-backed job queue — all work is synchronous, command-line driven

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
| `/admin/semantic-models/{model_id}` | GET | Get semantic model detail |
| `/admin/semantic-models/{model_id}/artifacts` | GET | List model artifacts |
| `/admin/semantic-datasets` | GET | List all datasets |
| `/admin/semantic-datasets/{dataset_id}` | GET | Get dataset detail |
| `/admin/semantic-datasets/{dataset_id}/artifacts` | GET | List dataset artifacts |

Filters on `/similar-cards`: `card_type`, `colors`, `cmc_min`, `cmc_max`, `format`, `rarity`, `color_feature` (`"identity"` | `"colors"`), `match_mode` (`"at_least"` | `"at_most"` | `"exact"`). `card_type` filters via array overlap on the GIN-indexed `type_categories` column; `matchMode` / `colorFeature` / `rarities` are allowlist-validated in `lib/filters.ts` before hitting the URL.

**Ability tuning** (card mode only): `include_abilities` / `exclude_abilities` on `/similar-cards` take comma-separated `ability_ix` values of the *seed* face (URL params `inc` / `exc`). Included abilities narrow the seed set; excluded ones ramp a candidate's score down across the `_REJECT_IGNORE_SIMILARITY`..`_REJECT_EXCLUDE_SIMILARITY` band (0.70..0.90) and drop it outright at the top. The band exists because cosine similarity between short ability texts has a ~0.7 floor — an unbanded penalty would shave every card and make the reported match percentage meaningless. Hand-picking an include subset switches scoring from bidirectional to forward/max-pool, on the same reasoning as text search. `/card/{oracle_id}` returns each face's segmented `abilities` (`ability_ix`, `text`, `is_keyword`) so the UI can offer the tri-state picker (`components/AbilityTuner.tsx`).

### Key files
- `api/main.py` — FastAPI app setup, lifespan, middleware, meta routes; includes routers; spawns `rotate_oracle_pools` background task
- `api/oracle_pool.py` — `load_oracle_pools`, `rotate_oracle_pools` (homepage sample refresh every `OT_ORACLE_POOL_REFRESH_SECONDS`)
- `api/routers/admin.py` — read-only `/admin/*` routes (auth + models/datasets + artifacts) and their serializers
- `api/routers/search.py` — `/search`, `/card/{oracle_id}`, `/similar-cards`, `/oracle-samples`
- `core/models.py` — ORM models (source of truth for the schema); composite PKs for card_faces, card_face_abilities and embeddings; pgvector `Vector` type
- `semantic/ability_split.py` — oracle-text → ability segmentation + `text_hash` dedup key; bakes Scryfall's keyword-ability catalog
- `core/db_init.py` — runs `alembic upgrade head` on every startup; session-level `pg_advisory_lock` held across Alembic; migration state FSM
- `ingest/scryfall_ingestion.py` — stale-aware Scryfall bulk ingest (gzipped JSON Lines via `jsonl_download_uri`), card derivation, `type_categories` extraction, ability segmentation; delete phase is a single transaction (no split-state on crash)
- `ingest/fetch_tags.py` — Scryfall Tagger GraphQL sync; `ThreadPoolExecutor` (default 6 workers) with per-thread sessions and a shared rate-limit semaphore
- `semantic/index.py` — runtime: lazy-loads ONNX model, encodes queries, two-stage ability retrieval (`_candidate_faces` → `_chamfer_rerank`) with server-side filters
- `semantic/model_registry.py` — model CRUD, materialization, bundle utilities
- `semantic/model_promotion.py` — `promote_semantic_model` end-to-end orchestration; atomic single-txn embedding replacement
- `semantic/artifacts.py` — S3 artifact upload/download and recording
- `semantic/bundle_registration.py` — bundle parsing and model registration
- `semantic/base_model_catalog.py` — base model listing and retrieval
- `semantic/semantic_state.py` — semantic data version tracking

### Local scripts
- `scripts/build_dataset.py` — CLI to build training datasets from Scryfall cards
- `scripts/train_model.py` — CLI to train a fine-tuned embedding model
- `scripts/promote_model.py` — CLI to materialize embeddings and activate a model
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
- Model bundles are stored in S3 (`SEMANTIC_ARTIFACT_BUCKET`) and cached locally in `SEMANTIC_TEMP_DIR`
- Homepage oracle/keyword pools are loaded at lifespan start and refreshed every `OT_ORACLE_POOL_REFRESH_SECONDS`

## Branch conventions

Two long-lived branches only:

- `develop` — default branch, full commit history. All work lands here.
- `production` — Railway deploys from this branch. Each commit is a tagged release squashed from `develop`.

Feature branches optional: `feat/<name>` / `fix/<name>`, merge into `develop`.

### Release flow

When `develop` is release-ready:

1. **Bump versions on develop first** so the release commit reflects the new version. Tag must match the version in both files.

   ```bash
   # edit backend/src/ot_backend/__init__.py (__version__) and frontend/package.json to vX.Y.Z
   # backend/pyproject.toml has NO version field — hatchling reads __version__
   # from the package, which is also what /version serves.
   uv lock --project backend                # refresh backend/uv.lock
   ( cd frontend && npm install )           # refresh frontend/package-lock.json
   git add backend/src/ot_backend/__init__.py backend/uv.lock frontend/package.json frontend/package-lock.json
   git commit -m "chore: bump version to X.Y.Z"
   git push origin develop
   ```

2. **Wait for CI green on develop** before cutting the release.

3. **Snapshot develop's tree onto production** and tag.

   ```bash
   git checkout production
   git pull --ff-only origin production
   git read-tree --reset -u develop         # overlay develop's tree onto the production index
   git commit -m "vX.Y.Z"
   git tag vX.Y.Z
   ```

   `git read-tree --reset -u develop` is used instead of `git merge --squash develop` because `--squash` doesn't record ancestry, so each subsequent release re-runs a 3-way merge against an ancient common ancestor and produces a storm of bogus add/add conflicts. The tree-overlay approach is content-equivalent and conflict-free.

4. **Merge production back into develop with `--no-ff`** so develop's history has a visible anchor pointing to the release. Without this, the next release's squash hits the same ancient-ancestor conflict storm.

   ```bash
   git checkout develop
   git merge --no-ff production -m "Merge tag vX.Y.Z into develop"
   ```

   Trees are identical, so the merge has no content delta — it just records the linkage.

5. **Push both branches and the tag.** Production first (kicks off Railway deploy), develop second.

   ```bash
   git push origin production --tags
   git push origin develop
   ```

Historical note: `v2.0.0` was cut without the merge-back step, so its production commit has no ancestry link to develop. The `v2.1.0` merge-back fixed the flow forward; releases from `v2.1.0` onward squash cleanly because git finds the previous release tag as the common ancestor.

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
| `OT_PUBLIC_URL` | — | Public origin (e.g. `https://oracletutor.org`); required for `/sitemap.xml` to emit canonical URLs, otherwise the route returns 404 |
| `SEMANTIC_TEMP_DIR` | `$TMPDIR/mtg-search-semantic-models` | Local cache for materialized model bundles |
| `SEMANTIC_ONNX_INTRA_OP_THREADS` | `1` | ONNX Runtime intra-op thread count |
| `SEMANTIC_ONNX_INTER_OP_THREADS` | `1` | ONNX Runtime inter-op thread count |
| `TAG_FETCH_CONCURRENCY` | `6` | Parallel workers for Scryfall Tagger sync |
| `ADMIN_PASSWORD` | — | Required for admin routes |
| `ADMIN_JWT_SECRET` | — | HS256 signing secret for admin bearer tokens |
| `ADMIN_LOGIN_MAX_FAILURES` | `5` | Failed admin logins per IP before lockout |
| `ADMIN_LOGIN_LOCKOUT_SECONDS` | `900` | Lockout duration after hitting the failure threshold |
| `CF_ACCESS_TEAM_DOMAIN` | — | Cloudflare Access team domain (e.g. `yourteam.cloudflareaccess.com`); enables Access JWT verification on `/admin/*` when set together with `CF_ACCESS_AUD` |
| `CF_ACCESS_AUD` | — | Cloudflare Access application AUD tag; required alongside `CF_ACCESS_TEAM_DOMAIN` |
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

## Pre-push secret audit

**Before any `git push` to a public remote, run a secret audit.** The repo is published on GitHub, so a single leaked credential in history is a rotation event — cheaper to catch before push than after.

Minimum check before pushing:

```bash
# Scan the range you're about to push
git diff origin/$(git rev-parse --abbrev-ref HEAD)...HEAD -- . ':(exclude)*.lock' ':(exclude)package-lock.json' \
  | grep -iE '(password|secret|api[_-]?key|token|bearer|authorization|private[_-]?key|aws_|database_url)=' \
  || echo "clean"

# Scan for committed env files or credential-shaped filenames
git diff --name-only origin/$(git rev-parse --abbrev-ref HEAD)...HEAD \
  | grep -iE '(^|/)(\.env($|\..+)|credentials|secrets|.*\.pem$|.*\.key$)' \
  || echo "clean"
```

If anything matches, stop and investigate before pushing. If a secret was ever committed (even in a past commit), rotate it *and* rewrite history with `git filter-repo` before the push — do not rely on "I'll just delete the next commit."

Secrets that must never appear in code or committed files: `ADMIN_PASSWORD`, `ADMIN_JWT_SECRET`, `SEMANTIC_ARTIFACT_ACCESS_KEY_ID`, `SEMANTIC_ARTIFACT_SECRET_ACCESS_KEY`, `DATABASE_URL` with real credentials, `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`.

## Rules

- Backend versioned independently from frontend: `backend/src/ot_backend/__init__.py` (`__version__`, the single source of truth `pyproject.toml` derives from) and `frontend/package.json`
- Worker is a one-shot container; runs daily via Railway Cron and exits
- Never run destructive Alembic migrations in production without reviewing the migration file first
- Tests run against a real Postgres (via testcontainers + `pgvector/pgvector:pg17`). Docker must be running locally and in CI.
- `DATABASE_URL` is always required (production, local, and Alembic CLI). No sqlite fallback anywhere.
- Source of truth for the schema is the ORM models in `core/models.py`; `0001_initial_schema.py` uses `Base.metadata.create_all()` plus explicit DDL for the GIN index, and later migrations add tables incrementally.
- **Because 0001 calls `create_all()` on live ORM metadata, it creates every table/column the ORM currently has — including ones a later migration is supposed to add.** Any migration that creates a table or adds a column MUST guard with `sa.inspect(bind)` first (see 0002, 0006, 0007), or fresh databases fail with DuplicateTable/DuplicateColumn. Spell columns out in the migration rather than reusing `Base.metadata`, so the migration stays a snapshot of that revision.
- No dialect branching in app code — Postgres is the only supported database.

# context-mode — MANDATORY routing rules

You have context-mode MCP tools available. These rules are NOT optional — they protect your context window from flooding. A single unrouted command can dump 56 KB into context and waste the entire session.

## BLOCKED commands — do NOT attempt these

### curl / wget — BLOCKED
Any Bash command containing `curl` or `wget` is intercepted and replaced with an error message. Do NOT retry.
Instead use:
- `ctx_fetch_and_index(url, source)` to fetch and index web pages
- `ctx_execute(language: "javascript", code: "const r = await fetch(...)")` to run HTTP calls in sandbox

### Inline HTTP — BLOCKED
Any Bash command containing `fetch('http`, `requests.get(`, `requests.post(`, `http.get(`, or `http.request(` is intercepted and replaced with an error message. Do NOT retry with Bash.
Instead use:
- `ctx_execute(language, code)` to run HTTP calls in sandbox — only stdout enters context

### WebFetch — BLOCKED
WebFetch calls are denied entirely. The URL is extracted and you are told to use `ctx_fetch_and_index` instead.
Instead use:
- `ctx_fetch_and_index(url, source)` then `ctx_search(queries)` to query the indexed content

## REDIRECTED tools — use sandbox equivalents

### Bash (>20 lines output)
Bash is ONLY for: `git`, `mkdir`, `rm`, `mv`, `cd`, `ls`, `npm install`, `pip install`, and other short-output commands.
For everything else, use:
- `ctx_batch_execute(commands, queries)` — run multiple commands + search in ONE call
- `ctx_execute(language: "shell", code: "...")` — run in sandbox, only stdout enters context

### Read (for analysis)
If you are reading a file to **Edit** it → Read is correct (Edit needs content in context).
If you are reading to **analyze, explore, or summarize** → use `ctx_execute_file(path, language, code)` instead. Only your printed summary enters context. The raw file content stays in the sandbox.

### Grep (large results)
Grep results can flood context. Use `ctx_execute(language: "shell", code: "grep ...")` to run searches in sandbox. Only your printed summary enters context.

## Tool selection hierarchy

1. **GATHER**: `ctx_batch_execute(commands, queries)` — Primary tool. Runs all commands, auto-indexes output, returns search results. ONE call replaces 30+ individual calls.
2. **FOLLOW-UP**: `ctx_search(queries: ["q1", "q2", ...])` — Query indexed content. Pass ALL questions as array in ONE call.
3. **PROCESSING**: `ctx_execute(language, code)` | `ctx_execute_file(path, language, code)` — Sandbox execution. Only stdout enters context.
4. **WEB**: `ctx_fetch_and_index(url, source)` then `ctx_search(queries)` — Fetch, chunk, index, query. Raw HTML never enters context.
5. **INDEX**: `ctx_index(content, source)` — Store content in FTS5 knowledge base for later search.

## Subagent routing

When spawning subagents (Agent/Task tool), the routing block is automatically injected into their prompt. Bash-type subagents are upgraded to general-purpose so they have access to MCP tools. You do NOT need to manually instruct subagents about context-mode.

## Output constraints

- Keep responses under 500 words.
- Write artifacts (code, configs, PRDs) to FILES — never return them as inline text. Return only: file path + 1-line description.
- When indexing content, use descriptive source labels so others can `ctx_search(source: "label")` later.

## ctx commands

| Command | Action |
|---------|--------|
| `ctx stats` | Call the `ctx_stats` MCP tool and display the full output verbatim |
| `ctx doctor` | Call the `ctx_doctor` MCP tool, run the returned shell command, display as checklist |
| `ctx upgrade` | Call the `ctx_upgrade` MCP tool, run the returned shell command, display as checklist |
