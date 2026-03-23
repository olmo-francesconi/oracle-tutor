# Pinboard

Shared communication board between the orchestrator (Claude) and Codex workers.

---

## Active Tasks

### TASK-001 — Infrastructure: DB pool + pgvector HNSW index
- **Files**: `backend/src/ot_backend/core/database.py`, `backend/src/ot_backend/core/db_init.py`
- **Changes**:
  1. `database.py`: Change pool defaults to `pool_size=3, max_overflow=2` (keep env var overrides via `DB_POOL_SIZE`, `DB_POOL_MAX_OVERFLOW`)
  2. `db_init.py`: In `_ensure_indexes()`, add HNSW index on `card_face_semantic_embeddings(embedding vector_cosine_ops)`:
     ```sql
     CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw
     ON card_face_semantic_embeddings USING hnsw (embedding vector_cosine_ops)
     ```

### TASK-002 — API main.py: request-path optimizations + filter pass-through + card cache
- **Files**: `backend/src/ot_backend/api/main.py`
- **Changes** (all in one file):
  1. **Schema-ready cache**: Add module-level `_schema_ready: bool = False`. In `_ensure_schema_ready()`, if `_schema_ready` is already `True`, return immediately (skip DB round-trip). On first successful check, set `global _schema_ready = True`.
  2. **`_is_postgres` startup detection**: Remove the `_is_postgres(db)` helper. At module level after imports, compute `_IS_POSTGRES: bool = engine.dialect.name == "postgresql"` (import `engine` from `..core.database`). Replace all `_is_postgres(db)` calls with `_IS_POSTGRES`.
  3. **N+1 fix in `_to_similar_cards`**: Add `from sqlalchemy.orm import joinedload` import. Change `db.query(CardFace).filter(CardFace.id.in_(target_face_ids)).all()` to `.options(joinedload(CardFace.card)).filter(...).all()` so card rows are fetched in one JOIN.
  4. **Card detail joinedload**: In `get_card_by_id`, replace `db.get(Card, card_id)` + `_ = card.faces` with `db.query(Card).options(joinedload(Card.faces)).filter(Card.id == card_id).first()`.
  5. **Filter pass-through**: In `get_similar_cards` and `search_oracle_text`, remove the `_ = (card_type, ...)` discard lines and pass the filter params to `index.similar_to_face(...)` and `index.search_oracle(...)` respectively.
  6. **TTL cache for card detail**: Add a module-level `_card_cache: dict[str, tuple[float, dict[str, object]]] = {}` and `CARD_CACHE_TTL = 3600.0`. In `get_card_by_id`, check cache first (skip expired), return cached result if fresh. Store result after fetching. Use `import time`.

### TASK-003 — embed/index.py: move hot-path imports to module level
- **Files**: `backend/src/ot_backend/embed/index.py`
- **Changes**:
  1. Remove `_load_semantic_model_class()` helper function entirely.
  2. Add `from ..core.models import CardFaceSemanticEmbedding, Card, CardFace` at module level (near the existing model import).
  3. Replace all calls to `_load_semantic_model_class()` with direct `CardFaceSemanticEmbedding` reference.
  4. Remove the internal `from ..core.models import Card, CardFace` inside `_pgvector_query`.

### TASK-004 — ingest/fetch_tags.py: tagger retry budget
- **Files**: `backend/src/ot_backend/ingest/fetch_tags.py`
- **Changes**:
  1. Add module-level constant `MAX_SESSION_RESETS = 5`.
  2. Wherever the session-reset-on-429 loop exists, add a reset counter. After `MAX_SESSION_RESETS` consecutive resets, log an error and break out of the loop (do not retry further for that card).

---

## Worker Status

<!-- Workers append their status here on start and completion -->
<!-- Format:
### TASK-001
- **Status**: in-progress | complete | blocked
- **Worker started**: YYYY-MM-DD HH:MM
- **Files touched**: list of files
- **Blocker** (if any): description
- **Result**: short summary of what was done
-->

### TASK-001
- **Status**: complete
- **Worker started**: 2026-03-23 21:16
- **Files touched**: `backend/src/ot_backend/core/database.py`, `backend/src/ot_backend/core/db_init.py`
- **Result**: Reduced Postgres pool defaults to 3/2 and added the HNSW index on `card_face_semantic_embeddings`


---

## Completed Work

<!-- Orchestrator moves completed tasks here after validation -->

---

## Notes & Decisions

- Base branch: `semantic-api`
- Feature branch: `feature/backend-api-optimizations`
- API must remain light: semantic index is optional (503 if unavailable), DB pool is small, no heavy startup work
- Tests run against SQLite in-memory; Postgres-specific paths (trigram, pgvector) are not covered by automated tests — do not break SQLite fallback paths
- `_IS_POSTGRES` is a module-level constant — safe to compute at import time because `engine` is already constructed at that point in `database.py`
- TTL cache in `get_card_by_id` does NOT need to be thread-safe for this deployment (single worker process)
