# Architecture: Oracle Tutor

## Overview
Three-service system: a one-shot **worker** ingests Scryfall card data into Postgres, the **API** serves search/similarity endpoints backed by an in-memory TF-IDF matrix, and the **frontend** is a React SPA proxied through nginx.

## Components

### Worker (`api/Dockerfile.worker`)
- Downloads Scryfall bulk JSON (streaming via `ijson`)
- Diffs new cards against existing DB rows (SQLAlchemy + psycopg 3)
- Posts to the API's internal `/internal/rebuild-tfidf` endpoint on completion
- Runs as a Railway Cron job (daily); exits after ingestion

### API (`api/src/oracle_tutor_api/`)
- **FastAPI + Hypercorn** — async HTTP server on port 8000
- **SQLAlchemy 2** ORM over PostgreSQL with pgvector extension
- **scikit-learn TF-IDF** — matrix built in-memory at startup and on rebuild trigger
- Key endpoints: `GET /search`, `GET /suggest-names`, `GET /search-oracle`, `GET /card/{id}`, `GET /similar-cards/{id}`, `POST /internal/rebuild-tfidf`, `GET /health`

### Frontend (`frontend/src/`)
- React 19 SPA with React Router 7
- Tanstack Query for server state; Framer Motion for animations
- Nginx serves static build and proxies `/api/*` → `http://api:8000`

### Database
- PostgreSQL 17 with pgvector extension
- Cards table stores Scryfall fields + EDHREC rank
- Schema migration guarded by `ORACLE_TUTOR_API_ALLOW_SCHEMA_RESET`

## Data flow
```
[Scryfall bulk data]
       ↓ (daily cron)
   [Worker]  →  Postgres (upsert cards)
                    ↓ (POST /internal/rebuild-tfidf)
               [API]  ←→  in-memory TF-IDF matrix
                    ↑
              [Frontend]  ←  nginx proxy (/api/*)
```

## Key decisions
- **TF-IDF in-memory** — fast cosine similarity without a vector DB; rebuilt in a subprocess (`ORACLE_TUTOR_API_TFIDF_REBUILD_IN_SUBPROCESS=1`) to reclaim RSS after build
- **Worker as one-shot container** — keeps ingestion isolated and stateless; Railway Cron restarts it daily
- **pgvector included** — available for future embedding-based search without schema changes
- **uv for Python deps** — deterministic lockfile (`uv.lock`), fast installs in Docker
