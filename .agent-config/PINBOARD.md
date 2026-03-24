# Pinboard

Shared communication board between the orchestrator (Claude) and Codex workers.

---

## Active Tasks

### ARCH-001 — Update ARCHITECTURE.md
Explore the codebase and update ARCHITECTURE.md to reflect current state before any implementation begins.
- **Status**: pending
- **Worker**: architect

### TASK-001 — Alembic setup
Add `alembic` dependency to `backend/pyproject.toml`, initialize `backend/alembic/` with `env.py` wired to our SQLAlchemy Base and `DATABASE_URL`, and write the initial migration (`0001_initial_schema.py`) that drops all existing tables and creates the full new schema in dependency order.
- **Scope**: `backend/pyproject.toml`, `backend/alembic/`
- **Status**: pending

### TASK-002 — Models rewrite
Rewrite `backend/src/ot_backend/core/models.py` to implement the new schema:
- `CardRaw` — 1:1 Scryfall bulk mirror, PK = scryfall UUID `id`, ~50 columns
- `Card` — oracle-deduplicated, PK = `oracle_id`, FK `scryfall_id → cards_raw.id`
- `CardFace` — composite PK `(oracle_id, face_ix)`, FK `oracle_id → cards.oracle_id`
- `CardFaceSemanticEmbedding` — composite PK/FK `(oracle_id, face_ix)`
- `CardTagging.card_id` and `CardRelationship.card_id` FKs → `cards.oracle_id`
- **Scope**: `backend/src/ot_backend/core/models.py`
- **Status**: pending
- **Depends on**: TASK-001

### TASK-003 — db_init + config updates
Replace `Base.metadata.create_all()` in `db_init.py` with Alembic `upgrade head`. Remove manual schema-version-bump drop logic.
- **Scope**: `backend/src/ot_backend/core/db_init.py`, `backend/src/ot_backend/core/config.py`
- **Status**: pending
- **Depends on**: TASK-001, TASK-002

### TASK-004 — Ingestion pipeline
Update `data_builder.py` and `fetch_tags.py`:
- Add `cards_raw` upsert for all printings; update card/face prep functions to use `oracle_id` PK and composite `(oracle_id, face_ix)`; update diff/delete logic to track oracle_id
- `fetch_tags.py`: resolve oracle_id via `cards_raw.id → cards.scryfall_id → cards.oracle_id` join when writing `card_taggings`
- **Scope**: `backend/src/ot_backend/ingest/data_builder.py`, `backend/src/ot_backend/ingest/fetch_tags.py`
- **Status**: pending
- **Depends on**: TASK-002

### TASK-005 — API + tests
Update `api/main.py` queries to use `oracle_id`. Update test fixtures and tests to match new schema (composite PKs, oracle_id, CardRaw).
- **Scope**: `backend/src/ot_backend/api/main.py`, `backend/tests/`
- **Status**: pending
- **Depends on**: TASK-002, TASK-003

---

## Worker Status

<!-- Workers append their status here on start and completion -->

### TASK-001 — Codex
- **Status**: complete
- **Started**: 2026-03-24
- **Files touched**: `.agent-config/PINBOARD.md`, `backend/pyproject.toml`, `backend/alembic/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/0001_initial_schema.py`
- **Result**: Added `alembic` to backend dependencies, initialized Alembic under `backend/alembic/`, wired `env.py` to `ot_backend.core.database.Base` with a `DATABASE_URL`/SQLite fallback, and added the initial dialect-aware migration for the new schema, Postgres trigram indexes, and pgvector HNSW index.

---

## Completed Work

<!-- Orchestrator moves completed tasks here after validation -->

---

## Notes & Decisions

- Base branch: `semantic-api` | Feature branch: `feat/scryfall-schema-refactor`
- **cards_raw**: stores ALL Scryfall printings (~300k rows); no navigation URIs; prices stored as JSONB snapshot; `ingested_at` timestamp per row
- **cards PK**: changed from Scryfall UUID → `oracle_id`. `cards.scryfall_id` points to the best printing in `cards_raw`
- **card_faces PK**: composite `(oracle_id, face_ix)` — replaces autoincrement integer id
- **CardFaceSemanticEmbedding PK**: composite `(oracle_id, face_ix)` — matches card_faces
- **Downstream FKs**: `card_taggings.card_id`, `card_relationships.card_id` → `cards.oracle_id`
- **Alembic**: replaces `create_all` + manual schema-version drop; initial migration does full drop+create
- **SQLite fallback for tests**: pgvector JSON fallback must be preserved; Alembic env.py must handle SQLite (skip Postgres-specific DDL like `CREATE EXTENSION pgvector`)
- **Tag association**: Tagger foreign_key is Scryfall UUID — fetch_tags must join through cards_raw to resolve oracle_id for card_taggings.card_id
