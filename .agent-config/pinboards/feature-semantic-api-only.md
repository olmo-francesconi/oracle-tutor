# Pinboard

Shared communication board between the orchestrator (Claude) and Codex workers.

---

## Active Tasks

### Feature: Semantic API Only — Remove TF-IDF

**Branch:** `feature/semantic-api-only` (from `semantic-api`)

**Goal:** Remove TF-IDF entirely. Promote semantic (pgvector + sentence-transformers) as the only search backend. Routes `/search-oracle` and `/similar-cards/{id}` stay the same paths but switch to semantic implementation. Add SQL filter parity. Clean up deps, config, docker, docs.

---

### TASK-000 — Architect: update ARCHITECTURE.md
- Reflect semantic-only architecture
- Remove TF-IDF references
- Document new data flow, components, key decisions

### TASK-A — Core API rewrite (main.py)
**Scope:** `api/src/oracle_tutor_api/api/`

Delete:
- `tfidf_index.py`
- `tfidf_build_standalone.py`
- `oracle_tokenizer.py`
- `semantic_router.py`

Rewrite `main.py` (~1400 → ~300 lines):
- Remove all TF-IDF globals, locks, rebuild state, helper functions, rebuild endpoints
- Remove imports: gc, hmac, pickle, resource, subprocess, sys, tempfile, threading, time, ipaddress, socket, Protocol, cast, TF-IDF modules
- Remove endpoints: POST /internal/rebuild-tfidf, old GET /search-oracle (TF-IDF), old GET /similar-cards/{id} (TF-IDF)
- Simplify lifespan: DB init + schema wait only
- Add GET /search-oracle and GET /similar-cards/{id} backed by SemanticIndex
- Add filter params: card_type, colors, cmc_min, cmc_max, format, rarity, color_feature (drop match_mode)
- Import semantic index from `..semantic.index`

### TASK-B — SemanticIndex filter support
**Scope:** `api/src/oracle_tutor_api/semantic/index.py`

Extend `_pgvector_query` to accept filter kwargs, JOIN with CardFace/Card:
- card_type: CardFace.type_line.ilike(f"%{value}%")
- colors/color_feature: CardFace.colors or Card.color_identity (JSON contains)
- cmc_min/cmc_max: Card.cmc >=/<= value
- format: Card.legalities JSON field contains format key with "legal"/"restricted"
- rarity: Card.rarity == value

Propagate through search_oracle() and similar_to_face().

### TASK-C — Config + worker cleanup
**Scope:** `api/src/oracle_tutor_api/core/config.py`, `api/src/oracle_tutor_api/worker/data_builder.py`

config.py: remove WORKER_TRIGGER_TOKEN, WORKER_TRIGGER_ALLOWLIST, WORKER_REBUILD_PATH, _get_worker_rebuild_path(), WORKER_REBUILD_TIMEOUT_SECONDS, API_BASE_URL

data_builder.py: remove _trigger_tfidf_rebuild_request(), trigger_tfidf_rebuild_best_effort(), and the call at end of ingestion. Remove related config imports.

### TASK-D — Dependencies + Docker cleanup
**Scope:** `api/pyproject.toml`, `api/Dockerfile`, `docker-compose.yml`, `docker-compose.prod.yml`

pyproject.toml:
- api extra: remove scikit-learn, cachetools, psutil; add sentence-transformers>=3.0
- worker extra: remove scikit-learn, cachetools
- remove semantic extra entirely (merged into api)
- test group: remove scikit-learn, cachetools

docker-compose.yml api service: remove ORACLE_TUTOR_API_MALLOC_TRIM, ORACLE_TUTOR_API_TFIDF_REBUILD_IN_SUBPROCESS, ORACLE_TUTOR_API_WORKER_TOKEN, ORACLE_TUTOR_API_WORKER_TRIGGER_ALLOWLIST, ORACLE_TUTOR_API_WORKER_REBUILD_PATH
docker-compose.yml worker service: remove ORACLE_TUTOR_API_BASE_URL, ORACLE_TUTOR_API_WORKER_TOKEN, ORACLE_TUTOR_API_WORKER_REBUILD_PATH, ORACLE_TUTOR_API_WORKER_REBUILD_TIMEOUT_SECONDS

api/Dockerfile: update extras install (no separate --extra semantic)

### TASK-E — Tests cleanup
**Scope:** `api/tests/`

Delete: `test_semantic_vs_tfidf.py`
Update `test_api.py`: remove test_search_oracle, test_search_oracle_long_text_not_penalized, test_search_oracle_digits_affect_ranking (TF-IDF ranking assertions, not valid for semantic)
Update `conftest.py`: remove TF-IDF fixture setup (index building)

### TASK-F — Docs + project files
**Scope:** `CLAUDE.md`, `ARCHITECTURE.md`, `.agent-config/shared.md`, `TODO.md`

CLAUDE.md:
- Update description: remove TF-IDF, highlight pgvector search
- Tech stack: remove scikit-learn (TF-IDF)
- Remove env vars: ORACLE_TUTOR_API_TFIDF_REBUILD_IN_SUBPROCESS, ORACLE_TUTOR_API_WORKER_TOKEN, ORACLE_TUTOR_API_WORKER_TRIGGER_ALLOWLIST, ORACLE_TUTOR_API_WORKER_REBUILD_PATH, ORACLE_TUTOR_API_WORKER_REBUILD_TIMEOUT_SECONDS

.agent-config/shared.md: update stack + architecture if TF-IDF referenced

TODO.md: update current focus to reflect semantic-only migration completed

## Worker Status

<!-- Workers append their status here on start and completion -->

### TASK-F
- Status: complete
- Worker: Codex
- Scope: `CLAUDE.md`, `.agent-config/shared.md`, `TODO.md`
- Summary: Updated project docs to reflect the semantic-only architecture and removed remaining TF-IDF references from the project guidance files.

### TASK-D
- Status: complete
- Worker: Codex
- Scope: `api/pyproject.toml`, `api/Dockerfile`, `docker-compose.yml`, `docker-compose.prod.yml`
- Summary: Removed TF-IDF-related dependencies from the `api`, `worker`, and `test` dependency sets, merged `sentence-transformers` into the `api` extra, removed the separate semantic extra install from `api/Dockerfile`, and cleaned the TF-IDF env vars from both compose files.

### TASK-C
- Status: complete
- Worker: Codex
- Scope: `api/src/oracle_tutor_api/core/config.py`, `api/src/oracle_tutor_api/worker/data_builder.py`
- Summary: Removed TF-IDF worker trigger config from `config.py`, deleted worker-side TF-IDF rebuild trigger helpers from `data_builder.py`, and removed the ingestion-end trigger call.

---

### TASK-A
- Status: complete
- Worker: Codex
- Scope: `api/src/oracle_tutor_api/api/`
- Summary: Deleted `tfidf_index.py`, `tfidf_build_standalone.py`, `oracle_tokenizer.py`, and `semantic_router.py`; rewrote `main.py` to use semantic search endpoints only and removed TF-IDF rebuild/state logic.

### TASK-B
- Status: complete
- Worker: Codex
- Scope: `api/src/oracle_tutor_api/semantic/index.py`
- Summary: Added optional filter kwargs to `search_oracle()`, `similar_to_face()`, and `_pgvector_query()`; implemented conditional `CardFace`/`Card` joins and SQL WHERE filters for `card_type`, `colors` (`identity` or `colors` feature), `cmc_min`, `cmc_max`, `format` legalities, and `rarity` while preserving lightweight no-filter query path.

### TASK-E
- Status: complete
- Worker: Codex
- Scope: `api/tests/`
- Summary: Deleted the standalone TF-IDF vs semantic comparison test file, removed TF-IDF ranking and rebuild endpoint tests from `test_api.py`, and stripped the TF-IDF environment setup from `conftest.py`.

---

## Completed Work

<!-- Orchestrator moves completed tasks here after validation -->

---

## Notes & Decisions

- Routes `/search-oracle` and `/similar-cards/{id}` keep same paths — frontend unchanged
- Frontend `api.ts` already calls these paths (no URL changes needed)
- `match_mode` filter param dropped (TF-IDF concept, not applicable to semantic)
- `color_feature` filter kept: 'identity' = Card.color_identity, 'colors' = CardFace.colors
- Model lives in API process, lazy-loaded from `data/semantic/model` on first request
- Card embeddings pre-computed offline by semantic-worker; query embedding computed on-the-fly
- TASK-E must run after TASK-A (tests reference route implementations)
