# Oracle Tutor

A fast, fuzzy-search engine for Magic: The Gathering cards, powering a REST API.

## Features

-   **Fuzzy Name Matching**: Finds cards even with typos or partial names using TF-IDF and cosine similarity.
-   **Smart Ranking**: Incorporates EDHREC rank to prioritize popular cards in search results.
-   **REST API**: FastAPI-based backend to integrate search into other applications.
-   **Local Data**: Downloads and indexes the latest Scryfall Oracle data for offline speed.

## Installation

1.  Clone the repository.
2.  Navigate to the API directory:
    ```bash
    cd api
    ```
3.  Install `uv` (once):
    ```bash
    # macOS (Homebrew)
    brew install uv

    # Or via the official installer (macOS/Linux)
    # curl -LsSf https://astral.sh/uv/install.sh | sh
    ```
4.  Create a virtual environment and install dependencies (locked via `uv.lock`):
    ```bash
    uv sync --extra api --extra worker
    ```

## Quick Start

### 1. Initialize Data
Before searching, you need to ingest the latest Scryfall Oracle bulk data into the database.

```bash
# From the api directory
uv run python -m ot_backend.ingest.main --strict --trigger-type manual
```

This stores bulk metadata/files under `api/data/` (optional) and ingests cards into Postgres.

### 2. Run the API Server
Start the HTTP API:

```bash
# From the api directory
uv run hypercorn ot_backend.api.main:app --reload --bind 0.0.0.0:8000
```

**Endpoints:**

-   `GET /search?q=lotus&limit=5` - Fuzzy search for cards by name.
-   `GET /suggest-names?q=lotus&limit=5` - Search for card names only.
-   `GET /search-oracle?q=deals%203%20damage&limit=20&offset=0` - Semantic-ish oracle text search.
-   `GET /card/{card_id}` - Fetch a full card (including faces).
-   `GET /similar-cards/{card_id}` - Find similar cards by oracle text.

**Example:**
```bash
curl "http://localhost:8000/search?q=black%20lotus&limit=5"
```

### 3. Run the Web Frontend (Optional)

A modern, interactive web frontend is available for easy searching:

```bash
cd frontend
npm ci --legacy-peer-deps
npm run dev
```

Then open your browser to `http://localhost:5173`.

The frontend features:
- Real-time autocomplete suggestions as you type
- Keyboard navigation (arrow keys, Enter, Escape)
- Beautiful, responsive UI
- See [frontend/README.md](frontend/README.md) for more details

## Railway Deployment Checklist

This repo is designed to deploy on Railway as **three services** (Frontend + API + Worker) plus **Railway Postgres**.

### 1) Create resources

- **Postgres**: add a Railway Postgres database to the project.
- **API service**: build from [`api/Dockerfile`](api/Dockerfile).
- **Worker service** (scheduled ingestion): build from [`api/Dockerfile.worker`](api/Dockerfile.worker).
- **Frontend service**: build from [`frontend/Dockerfile`](frontend/Dockerfile) (nginx runtime serves `dist/` and proxies `/api`).

### 2) Set environment variables

Set these in Railway (do not rely on local defaults):

- **API service**
  - `DATABASE_URL` = Railway Postgres connection string
  - `ORACLE_TUTOR_API_ENV=production`
  - *(optional)* `ORACLE_TUTOR_API_CORS_ORIGINS=` leave unset for same-origin; if you ever need cross-origin, set a comma-separated allowlist.
  - *(optional)* `ORACLE_TUTOR_LOG_TO_FILES=true` only if you want `/app/data/*.log` in addition to stdout.
  - `PORT` is injected by Railway automatically; the Dockerfile listens on it.

- **Worker service**
  - `DATABASE_URL` = same Railway Postgres connection string
  - `ORACLE_TUTOR_API_ENV=production`
  - Configure a **Railway Cron** schedule for this service (recommended), e.g. `0 2 * * *` (UTC unless you set a timezone).
  - The worker is a **one-shot command** (it runs the stale-aware update once and exits). The default container command is equivalent to:
    - `python -m ot_backend.ingest.main --strict --trigger-type cron`

- **Frontend service**
  - `API_PROXY_TARGET` = the API service internal URL (or your private service DNS if you use one)
  - `PORT` is typically injected by Railway automatically (nginx listens on `${PORT}`).

### 3) Confirm routing (same-origin)

- Frontend should call the API as **`/api/...`** (same-origin).
- Nginx in the frontend container rewrites `/api/<path>` → `/<path>` and proxies to `API_PROXY_TARGET`.

### 4) Health checks / smoke tests

- **API**: `GET /health` returns `{"status":"ok"}`.
- **Frontend**: loads and can query suggestions (network call should be to `/api/suggest-names?...`).

### 5) Operational gotchas (recommended defaults)

- **Do not run the scheduler in the API service** on Railway (it can duplicate work across restarts/replicas). Keep scheduled ingestion in the Worker.
- **DATABASE_URL is required on Railway**: the API treats Railway as production to avoid insecure defaults.

## Daily Updates

The card database can be kept in sync with Scryfall's latest data. When updates are available, the system will:
1. Download the latest bulk data from Scryfall
2. Diff-ingest changes into Postgres
3. The API notices the DB version change and rebuilds its in-memory TF-IDF index (throttled polling)

### Recommended: Railway Cron + one-shot worker

On Railway, the recommended approach is:
- **API service**: web process only (no scheduled ingestion in the web container)
- **Worker service**: triggered by a **Railway Cron** schedule once per day

The worker command runs the stale-aware update once and exits:

```bash
python -m ot_backend.ingest.main --strict --trigger-type cron
```

### Local / self-hosted cron

If you want to schedule updates yourself, run the same one-shot command via your system cron (or use docker-compose):

```bash
# From the api directory
python -m ot_backend.ingest.main --strict --trigger-type cron
```

Or with Docker (from repo root):

```bash
docker compose run --rm worker
```

## How It Works

-   **Data Source**: Consumes Scryfall's `oracle_cards` bulk data.
-   **Search Algorithm**: Uses `scikit-learn` to build a TF-IDF matrix of card name n-grams. Queries are matched using cosine similarity against this matrix, with a boost factor for cards with higher EDHREC ranks.

## License

This project is licensed under the terms of the [GNU General Public License v3.0](LICENSE).
