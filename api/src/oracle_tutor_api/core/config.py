from __future__ import annotations

from pathlib import Path

# Project root is /api (since this file lives in /api/src/oracle_tutor_api)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
CARDS_JSON = DATA_DIR / "cards.json"

# Semantic Versioning for DB Schema (Major.Minor.Patch)
# Increment Major for breaking DB changes requiring full rebuild.
DB_SCHEMA_VERSION = "0.1.0"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


