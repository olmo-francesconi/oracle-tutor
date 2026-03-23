from __future__ import annotations

import os
from pathlib import Path

# Project root is /api (since this file lives in /api/src/oracle_tutor_api/core)
PROJECT_ROOT = Path(__file__).resolve().parents[3]

DATA_DIR = PROJECT_ROOT / "data"
CARDS_JSON = DATA_DIR / "cards.json"

# Semantic Versioning for DB Schema (Major.Minor.Patch)
# Increment Major for breaking DB changes requiring full rebuild.
DB_SCHEMA_VERSION = "2.5.0"

# Dangerous operation guard:
# Full table resets are disabled by default and must be explicitly enabled.
ALLOW_SCHEMA_RESET = os.getenv("ORACLE_TUTOR_API_ALLOW_SCHEMA_RESET", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# API startup migration wait behavior
SCHEMA_WAIT_TIMEOUT_SECONDS = float(os.getenv("ORACLE_TUTOR_API_SCHEMA_WAIT_TIMEOUT_SECONDS", "30"))
SCHEMA_WAIT_INTERVAL_SECONDS = float(os.getenv("ORACLE_TUTOR_API_SCHEMA_WAIT_INTERVAL_SECONDS", "1"))


def parse_version(version_str: str | None) -> tuple[int, int, int]:
    if not version_str:
        return (0, 0, 0)
    try:
        parts = version_str.split(".")
        # Handle cases like "0.1" by padding with zeros
        while len(parts) < 3:
            parts.append("0")
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return (0, 0, 0)


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
