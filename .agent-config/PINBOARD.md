# Pinboard

Shared communication board between the orchestrator (Claude) and Codex workers.

---

## Active Tasks

### ARCH-001 — Update ARCHITECTURE.md
Reflect current module structure before rename workers begin.

### TASK-001 — Filesystem rename + pyproject.toml
- Rename `api/src/oracle_tutor_api/` → `api/src/ot_backend/`
- Rename `api/src/ot_backend/worker/` → `api/src/ot_backend/ingest/`
- Rename `api/src/ot_backend/semantic/` → `api/src/ot_backend/embed/`
- Update `api/pyproject.toml`: `name = "oracle-tutor-api"` → `name = "ot-backend"`
- **Scope**: `api/src/`, `api/pyproject.toml`

### TASK-002 — Update Python source logger strings
- In all files under `api/src/ot_backend/`, replace `getLogger("oracle_tutor_api.*")` strings with `getLogger("ot_backend.*")`
- Also update `worker` → `ingest` and `semantic` → `embed` in logger names
- **Scope**: `api/src/ot_backend/`

### TASK-003 — Update test files and scripts
- Replace all `from oracle_tutor_api.*` imports with `from ot_backend.*`
- Apply module renames: `worker` → `ingest`, `semantic` → `embed`
- **Scope**: `api/tests/`, `api/scripts/`

### TASK-004 — Update Dockerfiles
- `api/Dockerfile`: update COPY paths and CMD entrypoint
- `api/Dockerfile.worker`: update COPY paths and CMD
- `api/Dockerfile.semantic-worker`: update COPY paths and CMD
- **Scope**: `api/Dockerfile`, `api/Dockerfile.worker`, `api/Dockerfile.semantic-worker`

### TASK-005 — Update CI, docker-compose, and docs
- `.github/workflows/api-ci.yml`, `.github/workflows/ci.yml`
- `docker-compose.yml`, `docker-compose.prod.yml`, `docker-compose.worker.yml` (only module path references, NOT env var names)
- `README.md`, `api/README.md`, `ARCHITECTURE.md`, `.agent-config/shared.md`, `CLAUDE.md`
- **Scope**: `.github/`, root docker-compose files, docs

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

---

## Completed Work

<!-- Orchestrator moves completed tasks here after validation -->

---

## Notes & Decisions

- **Rename map**: `oracle_tutor_api` → `ot_backend`, `worker/` → `ingest/`, `semantic/` → `embed/`, `api/` and `core/` unchanged
- **Env vars NOT renamed**: `ORACLE_TUTOR_API_*` env var names stay as-is — they affect Railway production config and will be changed separately
- **Base branch**: `semantic-api`
- **Feature branch**: `feature/rename-ot-backend`
