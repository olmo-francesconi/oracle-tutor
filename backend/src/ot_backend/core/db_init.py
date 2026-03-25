from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic.config import Config
from sqlalchemy import inspect, text

from alembic import command

from .config import DB_SCHEMA_VERSION
from .database import engine

logger = logging.getLogger("ot_backend.db")

INIT_MODE_API = "api"
INIT_MODE_WORKER = "worker"

SCHEMA_LOCK_KEY = 8462751100339012
MIGRATION_STATE_KEY = "schema_migration"
MIGRATION_STATE_READY = "ready"
MIGRATION_STATE_MIGRATING = "migrating"
MIGRATION_STATE_FAILED = "failed"


def _utcnow_naive() -> datetime:
    """Return naive UTC datetime without using deprecated utcnow()."""
    return datetime.now(UTC).replace(tzinfo=None)


def _acquire_schema_lock(conn, dialect: str) -> None:
    if dialect != "postgresql":
        return
    conn.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": SCHEMA_LOCK_KEY})


def _set_migration_state(conn, *, state: str, target_version: str) -> None:
    now = _utcnow_naive()
    conn.execute(
        text(
            """
            INSERT INTO system_metadata (key, data_updated_at, last_ingestion, schema_version)
            VALUES (:key, :data_updated_at, :last_ingestion, :schema_version)
            ON CONFLICT(key) DO UPDATE SET
                data_updated_at = excluded.data_updated_at,
                last_ingestion = excluded.last_ingestion,
                schema_version = excluded.schema_version
            """
        ),
        {
            "key": MIGRATION_STATE_KEY,
            "data_updated_at": state,
            "last_ingestion": now,
            "schema_version": target_version,
        },
    )


def get_migration_state() -> str:
    with engine.begin() as conn:
        inspector = inspect(conn)
        if not inspector.has_table("system_metadata"):
            return MIGRATION_STATE_READY
        row = conn.execute(
            text("SELECT data_updated_at FROM system_metadata WHERE key = :key"),
            {"key": MIGRATION_STATE_KEY},
        ).fetchone()
        if not row or not row[0]:
            return MIGRATION_STATE_READY
        return str(row[0])


def wait_for_migration_ready(*, timeout_s: float, interval_s: float = 1.0) -> bool:
    deadline = _utcnow_naive() + timedelta(seconds=max(0.0, timeout_s))
    wait_seconds = max(interval_s, 0.1)
    logged_waiting = False
    while _utcnow_naive() <= deadline:
        state = get_migration_state()
        if state == MIGRATION_STATE_READY:
            return True
        if state == MIGRATION_STATE_FAILED:
            logger.warning("Schema migration state is FAILED — data endpoints will return 503")
            return False
        if not logged_waiting:
            logger.info("Schema migration in progress (state=%s), waiting up to %.0fs...", state, timeout_s)
            logged_waiting = True
        time.sleep(wait_seconds)
    state = get_migration_state()
    if state != MIGRATION_STATE_READY:
        logger.warning("Schema migration timed out after %.0fs (state=%s)", timeout_s, state)
    return state == MIGRATION_STATE_READY


def _upsert_schema_version(conn, schema_version: str) -> None:
    now = _utcnow_naive()
    existing_row = conn.execute(
        text("SELECT data_updated_at FROM system_metadata WHERE key = 'scryfall_data'")
    ).fetchone()
    existing_updated_at = ""
    if existing_row and existing_row[0]:
        existing_updated_at = str(existing_row[0])
    conn.execute(
        text(
            """
            INSERT INTO system_metadata (key, data_updated_at, last_ingestion, schema_version)
            VALUES (:key, :data_updated_at, :last_ingestion, :schema_version)
            ON CONFLICT(key) DO UPDATE SET
                data_updated_at = excluded.data_updated_at,
                last_ingestion = excluded.last_ingestion,
                schema_version = excluded.schema_version
            """
        ),
        {
            "key": "scryfall_data",
            "data_updated_at": existing_updated_at,
            "last_ingestion": now,
            "schema_version": schema_version,
        },
    )


def _alembic_ini_path() -> Path:
    return Path(__file__).resolve().parents[3] / "alembic" / "alembic.ini"


def _build_alembic_config() -> Config:
    alembic_ini = _alembic_ini_path()
    if not alembic_ini.exists():
        raise FileNotFoundError(f"Alembic config not found: {alembic_ini}")
    return Config(str(alembic_ini))


def _upgrade_schema_to_head() -> None:
    alembic_cfg = _build_alembic_config()
    command.upgrade(alembic_cfg, "head")


def init_db(mode: str = INIT_MODE_API) -> None:
    """
    Initialize DB schema.

    - Use Alembic migrations to reach schema head.
    - Keep advisory lock for concurrency safety.
    """
    if mode not in (INIT_MODE_API, INIT_MODE_WORKER):
        raise ValueError(f"Unsupported init_db mode: {mode}")
    logger.info("Initializing database...")

    try:
        with engine.begin() as conn:
            dialect = conn.dialect.name
            _acquire_schema_lock(conn, dialect)
            inspector = inspect(conn)
            if mode == INIT_MODE_WORKER and inspector.has_table("system_metadata"):
                _set_migration_state(conn, state=MIGRATION_STATE_MIGRATING, target_version=DB_SCHEMA_VERSION)
        _upgrade_schema_to_head()
        if mode == INIT_MODE_WORKER:
            with engine.begin() as conn:
                _upsert_schema_version(conn, DB_SCHEMA_VERSION)
                _set_migration_state(conn, state=MIGRATION_STATE_READY, target_version=DB_SCHEMA_VERSION)
    except Exception:
        # Persist failed state in a separate transaction. If we wrote this inside the failed
        # transaction it would be rolled back alongside the original error.
        if mode == INIT_MODE_WORKER:
            try:
                with engine.begin() as fail_conn:
                    fail_inspector = inspect(fail_conn)
                    if fail_inspector.has_table("system_metadata"):
                        _set_migration_state(
                            fail_conn,
                            state=MIGRATION_STATE_FAILED,
                            target_version=DB_SCHEMA_VERSION,
                        )
            except Exception:
                logger.exception("Failed to persist schema migration failed state.")
        raise

    logger.info("Database initialized (mode=%s).", mode)
