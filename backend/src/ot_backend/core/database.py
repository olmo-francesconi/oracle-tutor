from __future__ import annotations

import os
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


def _is_production() -> bool:
    env = os.getenv("ORACLE_TUTOR_API_ENV", "development").lower()
    if env in ("prod", "production"):
        return True

    # Railway detection: treat Railway deployments as production even if the app-specific
    # env var wasn't set, to avoid accidentally booting with insecure local defaults.
    if any(
        os.getenv(k)
        for k in (
            "RAILWAY_ENVIRONMENT",
            "RAILWAY_PROJECT_ID",
            "RAILWAY_SERVICE_ID",
            "RAILWAY_PUBLIC_DOMAIN",
        )
    ):
        return True
    return False


def _build_database_url() -> str:
    # Allows tests and power users to bypass DB_* envs entirely.
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit

    # Production should be configured via DATABASE_URL (Railway-friendly).
    if _is_production():
        raise RuntimeError("DATABASE_URL is required in production (set ORACLE_TUTOR_API_ENV=production).")

    # Local/dev defaults match docker-compose.yml in repo root.
    user = os.getenv("DB_USER", "oracle")
    password = os.getenv("DB_PASSWORD")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "mtg_search")

    if not password:
        raise RuntimeError("DB_PASSWORD must be set when DATABASE_URL is not provided.")
    if password == "secret_password" and _is_production():
        raise RuntimeError("Refusing to start with placeholder DB_PASSWORD in production.")

    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


DATABASE_URL = _build_database_url()

# Future note: if we ever use async SQLAlchemy, this needs to change.
#
# Tests often use sqlite :memory:, which requires a StaticPool to keep one connection alive
# across the whole process.
_engine_kwargs: dict[str, Any] = {
    "pool_pre_ping": True,
    "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "3600")),  # recycle connections after 1 hour
}

if DATABASE_URL.startswith("sqlite") and ":memory:" in DATABASE_URL:
    _engine_kwargs.update(
        {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        }
    )
else:
    # Connection pool settings for Postgres to handle high concurrency
    # Defaults: pool_size=5, max_overflow=10 (total: 15 connections)
    _engine_kwargs.update({
        "pool_size": int(os.getenv("DB_POOL_SIZE", "3")),
        "max_overflow": int(os.getenv("DB_POOL_MAX_OVERFLOW", "2")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),  # seconds to wait for connection
    })

engine = create_engine(DATABASE_URL, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
