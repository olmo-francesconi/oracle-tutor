from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Project root is /backend (since this file lives in /backend/src/ot_backend/core)
PROJECT_ROOT = Path(__file__).resolve().parents[3]

DATA_DIR = PROJECT_ROOT / "data"
CARDS_JSON = DATA_DIR / "cards.json"
DEFAULT_HF_CACHE_DIR = DATA_DIR / "huggingface"
DEFAULT_SEMANTIC_BASE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_SEMANTIC_RUNS_DIR = Path("data/semantic/runs")

# Semantic Versioning for DB Schema (Major.Minor.Patch)
# Increment Major for breaking DB changes requiring full rebuild.
DB_SCHEMA_VERSION = "3.0.0"

# API startup migration wait behavior
SCHEMA_WAIT_TIMEOUT_SECONDS = float(os.getenv("ORACLE_TUTOR_API_SCHEMA_WAIT_TIMEOUT_SECONDS", "30"))
SCHEMA_WAIT_INTERVAL_SECONDS = float(os.getenv("ORACLE_TUTOR_API_SCHEMA_WAIT_INTERVAL_SECONDS", "1"))
DEFAULT_ALLOWED_HOSTS: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver", "api")
MAX_REQUEST_BYTES = int(os.getenv("ORACLE_TUTOR_API_MAX_REQUEST_BYTES", "32768"))
SEMANTIC_ADMIN_MAX_REQUEST_BYTES = int(os.getenv("SEMANTIC_ADMIN_MAX_REQUEST_BYTES", str(64 * 1024 * 1024)))
MAX_QUERY_LENGTH = int(os.getenv("ORACLE_TUTOR_API_MAX_QUERY_LENGTH", "200"))


def oracle_tutor_env() -> str:
    return os.getenv("ORACLE_TUTOR_API_ENV", "development").lower()


def admin_password() -> str | None:
    return os.getenv("ADMIN_PASSWORD")


def admin_jwt_secret() -> str | None:
    return os.getenv("ADMIN_JWT_SECRET")


def admin_login_max_failures() -> int:
    return max(1, int(os.getenv("ADMIN_LOGIN_MAX_FAILURES", "5")))


def admin_login_lockout_seconds() -> int:
    return max(1, int(os.getenv("ADMIN_LOGIN_LOCKOUT_SECONDS", "900")))


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


def allowed_hosts() -> list[str]:
    explicit = os.getenv("ORACLE_TUTOR_API_ALLOWED_HOSTS", "").strip()
    def normalize(host: str) -> str:
        return host.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0].strip()

    if explicit:
        return [normalized for host in explicit.split(",") if (normalized := normalize(host))]

    hosts: list[str] = list(DEFAULT_ALLOWED_HOSTS)
    for env_key in ("RAILWAY_PUBLIC_DOMAIN", "RAILWAY_PRIVATE_DOMAIN"):
        host = normalize(os.getenv(env_key, ""))
        if host:
            hosts.append(host)

    return hosts


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def semantic_base_model_name() -> str:
    return os.getenv("SEMANTIC_BASE_MODEL", DEFAULT_SEMANTIC_BASE_MODEL)



def semantic_active_model_poll_seconds() -> float:
    return float(os.getenv("SEMANTIC_ACTIVE_MODEL_POLL_SECONDS", "5"))


def semantic_onnx_intra_op_threads() -> int:
    return max(1, int(os.getenv("SEMANTIC_ONNX_INTRA_OP_THREADS", "1")))


def semantic_onnx_inter_op_threads() -> int:
    return max(1, int(os.getenv("SEMANTIC_ONNX_INTER_OP_THREADS", "1")))


def semantic_job_heartbeat_seconds() -> float:
    return float(os.getenv("SEMANTIC_JOB_HEARTBEAT_SECONDS", "600"))


def semantic_job_stale_seconds() -> float:
    return float(os.getenv("SEMANTIC_JOB_STALE_SECONDS", "1200"))


def semantic_train_max_jobs_per_run() -> int:
    return int(os.getenv("SEMANTIC_TRAIN_MAX_JOBS_PER_RUN", "1"))


def semantic_promote_max_jobs_per_run() -> int:
    return int(os.getenv("SEMANTIC_PROMOTE_MAX_JOBS_PER_RUN", "50"))


def semantic_temp_dir() -> Path:
    return Path(os.getenv("SEMANTIC_TEMP_DIR", str(Path(tempfile.gettempdir()) / "mtg-search-semantic-models")))


def modal_token_id() -> str | None:
    return os.getenv("MODAL_TOKEN_ID")


def modal_token_secret() -> str | None:
    return os.getenv("MODAL_TOKEN_SECRET")


def modal_client_configured() -> bool:
    return bool(modal_token_id() and modal_token_secret())


def semantic_llm_model_name() -> str:
    return os.getenv("SEMANTIC_LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")


def semantic_llm_max_queries_per_face() -> int:
    return max(1, int(os.getenv("SEMANTIC_LLM_MAX_QUERIES_PER_FACE", "3")))


def semantic_llm_max_faces() -> int:
    return max(1, int(os.getenv("SEMANTIC_LLM_MAX_FACES", "2500")))


def semantic_llm_min_template_coverage() -> int:
    return max(0, int(os.getenv("SEMANTIC_LLM_MIN_TEMPLATE_COVERAGE", "2")))


def semantic_llm_temperature() -> float:
    return float(os.getenv("SEMANTIC_LLM_TEMPERATURE", "0.6"))


def semantic_llm_max_tokens() -> int:
    return max(32, int(os.getenv("SEMANTIC_LLM_MAX_TOKENS", "500")))


def artifact_bucket_client():
    import boto3
    from botocore.client import Config

    return boto3.client(
        "s3",
        endpoint_url=os.environ["SEMANTIC_ARTIFACT_ENDPOINT"],
        aws_access_key_id=os.environ["SEMANTIC_ARTIFACT_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["SEMANTIC_ARTIFACT_SECRET_ACCESS_KEY"],
        region_name=os.getenv("SEMANTIC_ARTIFACT_REGION", "auto"),
        config=Config(signature_version="s3v4"),
    )


def artifact_bucket_name() -> str:
    return os.environ["SEMANTIC_ARTIFACT_BUCKET"]


def huggingface_cache_dir() -> Path:
    cache_dir = Path(os.getenv("HF_HOME", str(DEFAULT_HF_CACHE_DIR)))
    cache_dir.mkdir(parents=True, exist_ok=True)
    _ = os.environ.setdefault("HF_HOME", str(cache_dir))
    _ = os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(cache_dir / "sentence-transformers"))
    return cache_dir
