from __future__ import annotations

import os
from pathlib import Path

# Project root is /backend (since this file lives in /backend/src/ot_backend/core)
PROJECT_ROOT = Path(__file__).resolve().parents[3]

DATA_DIR = PROJECT_ROOT / "data"
CARDS_JSON = DATA_DIR / "cards.json"
DEFAULT_HF_CACHE_DIR = DATA_DIR / "huggingface"
DEFAULT_SEMANTIC_BASE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_SEMANTIC_RUNS_DIR = Path("data/semantic/runs")
DEFAULT_SEMANTIC_MODEL_PATH = DEFAULT_SEMANTIC_RUNS_DIR / "latest" / "models" / "onnx"
DEFAULT_SEMANTIC_ONNX_RELATIVE_PATH = Path("onnx/model.onnx")

# Semantic Versioning for DB Schema (Major.Minor.Patch)
# Increment Major for breaking DB changes requiring full rebuild.
DB_SCHEMA_VERSION = "2.5.0"

# API startup migration wait behavior
SCHEMA_WAIT_TIMEOUT_SECONDS = float(os.getenv("ORACLE_TUTOR_API_SCHEMA_WAIT_TIMEOUT_SECONDS", "30"))
SCHEMA_WAIT_INTERVAL_SECONDS = float(os.getenv("ORACLE_TUTOR_API_SCHEMA_WAIT_INTERVAL_SECONDS", "1"))


def oracle_tutor_env() -> str:
    return os.getenv("ORACLE_TUTOR_API_ENV", "development").lower()


def is_production_env() -> bool:
    env = oracle_tutor_env()
    if env in ("prod", "production"):
        return True
    return any(
        os.getenv(key)
        for key in (
            "RAILWAY_ENVIRONMENT",
            "RAILWAY_PROJECT_ID",
            "RAILWAY_SERVICE_ID",
            "RAILWAY_PUBLIC_DOMAIN",
        )
    )


def parse_version(version_str: str | None) -> tuple[int, int, int]:
    if not version_str:
        return (0, 0, 0)
    try:
        parts = version_str.split(".")
        # Handle cases like "0.1" by padding with zeros
        while len(parts) < 3:
            parts.append("0")
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return (0, 0, 0)


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def semantic_model_path() -> Path:
    return Path(os.getenv("SEMANTIC_MODEL_PATH", str(DEFAULT_SEMANTIC_MODEL_PATH)))


def semantic_onnx_model_path() -> Path:
    model_root = semantic_model_path()
    default_path = model_root / DEFAULT_SEMANTIC_ONNX_RELATIVE_PATH
    legacy_path = model_root / "model.onnx"
    if default_path.exists():
        return default_path
    if legacy_path.exists():
        return legacy_path
    return default_path


def semantic_base_model_name() -> str:
    return os.getenv("SEMANTIC_BASE_MODEL", DEFAULT_SEMANTIC_BASE_MODEL)


def semantic_model_source() -> str:
    model_path = semantic_model_path()
    if model_path.exists():
        return str(model_path)
    return semantic_base_model_name()


def huggingface_cache_dir() -> Path:
    cache_dir = Path(os.getenv("HF_HOME", str(DEFAULT_HF_CACHE_DIR)))
    cache_dir.mkdir(parents=True, exist_ok=True)
    _ = os.environ.setdefault("HF_HOME", str(cache_dir))
    _ = os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(cache_dir / "sentence-transformers"))
    return cache_dir
