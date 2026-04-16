from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import is_production_env

# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------

def _build_database_url() -> str:
    # Allows tests and power users to bypass DB_* envs entirely.
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit

    # Production should be configured via DATABASE_URL (Railway-friendly).
    if is_production_env():
        raise RuntimeError("DATABASE_URL is required in production (set OT_ENV=production).")

    # Local/dev defaults match docker-compose.yml in repo root.
    user = os.getenv("DB_USER", "oracle")
    password = os.getenv("DB_PASSWORD")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "mtg_search")

    if not password:
        raise RuntimeError("DB_PASSWORD must be set when DATABASE_URL is not provided.")
    if password == "secret_password" and is_production_env():
        raise RuntimeError("Refusing to start with placeholder DB_PASSWORD in production.")

    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


DATABASE_URL = _build_database_url()


# ---------------------------------------------------------------------------
# Engine setup
# ---------------------------------------------------------------------------

# Future note: if we ever use async SQLAlchemy, this needs to change.
#
# Tests often use sqlite :memory:, which requires a StaticPool to keep one connection alive
# across the whole process.
def _create_engine(database_url: str) -> Engine:
    pool_recycle_seconds = int(os.getenv("DB_POOL_RECYCLE", "3600"))
    if database_url.startswith("sqlite") and ":memory:" in database_url:
        return create_engine(
            database_url,
            pool_pre_ping=True,
            pool_recycle=pool_recycle_seconds,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=pool_recycle_seconds,
        pool_size=int(os.getenv("DB_POOL_SIZE", "3")),
        max_overflow=int(os.getenv("DB_POOL_MAX_OVERFLOW", "2")),
        pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
    )


engine = _create_engine(DATABASE_URL)


# ---------------------------------------------------------------------------
# Session / Base
# ---------------------------------------------------------------------------

SessionLocal = sessionmaker[Session](autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
