## Barebones FastAPI (`/api`)

This folder contains a minimal FastAPI service managed by **uv**.

### Local dev

- **Install uv** (if you don't have it):
  - `curl -LsSf https://astral.sh/uv/install.sh | sh`

- **Create venv + install deps**:
  - `cd api`
  - `uv sync`

- **Run the API**:
  - `uv run uvicorn oracle_tutor_api.main:app --reload --host 0.0.0.0 --port 8000`

### Tests

- **Install test deps**:
  - `cd api`
  - `uv sync --group test`

- **Run**:
  - `uv run pytest`

Endpoints:
- `GET /` -> basic service info
- `GET /health` -> health check

### Docker

From the repo root:

- **Build**:
  - `docker build -t oracle-tutor-api -f api/Dockerfile api`

- **Run**:
  - `docker run --rm -p 8000:8000 oracle-tutor-api`


