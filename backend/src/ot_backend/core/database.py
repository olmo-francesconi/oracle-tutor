from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import is_production_env

# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------

def _build_database_url() -> str:
    # Allows tests and power users to bypass DB_* envs entirely.
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        # Railway and most Postgres providers hand back `postgresql://...` with
        # no driver suffix. SQLAlchemy maps that to psycopg2, which we don't
        # install (we ship psycopg v3 only). Force the psycopg-3 dialect.
        if explicit.startswith("postgresql://"):
            return "postgresql+psycopg://" + explicit[len("postgresql://"):]
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

def _pool_defaults_for_role() -> tuple[int, int]:
    """Role-aware pool defaults.

    API serves concurrent requests and needs headroom for the pgvector query
    that pins a connection per /similar-cards call. The ingest worker is a
    one-shot container that uses 1-2 connections; sizing it like the API
    just wastes Postgres backends.
    """
    role = os.getenv("OT_SERVICE_ROLE", "api").strip().lower()
    if role == "worker":
        return 2, 1
    return 10, 5


def _create_engine(database_url: str) -> Engine:
    pool_recycle_seconds = int(os.getenv("DB_POOL_RECYCLE", "3600"))
    default_pool_size, default_max_overflow = _pool_defaults_for_role()
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=pool_recycle_seconds,
        pool_size=int(os.getenv("DB_POOL_SIZE", str(default_pool_size))),
        max_overflow=int(os.getenv("DB_POOL_MAX_OVERFLOW", str(default_max_overflow))),
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
