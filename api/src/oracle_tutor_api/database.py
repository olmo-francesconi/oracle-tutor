from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


def _build_database_url() -> str:
    # Allows tests and power users to bypass DB_* envs entirely.
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit

    # Defaults match docker-compose.yml in repo root.
    user = os.getenv("DB_USER", "oracle")
    password = os.getenv("DB_PASSWORD", "secret_password")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "mtg_search")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


DATABASE_URL = _build_database_url()

# Future note: if we ever use async SQLAlchemy, this needs to change.
#
# Tests often use sqlite :memory:, which requires a StaticPool to keep one connection alive
# across the whole process.
_engine_kwargs = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite") and ":memory:" in DATABASE_URL:
    _engine_kwargs.update(
        {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        }
    )

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


