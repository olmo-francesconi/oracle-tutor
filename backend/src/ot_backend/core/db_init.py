from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from alembic.config import Config
from sqlalchemy import Connection, inspect, text

from alembic import command

from .config import DB_SCHEMA_VERSION, SCRYFALL_DATA_KEY
from .database import engine
from .models import utcnow_naive

logger = logging.getLogger("ot_backend.db")


def parse_version(version_str: str | None) -> tuple[int, int, int]:
    if not version_str:
        return (0, 0, 0)
    try:
        parts = version_str.split(".")
        while len(parts) < 3:
            parts.append("0")
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return (0, 0, 0)

INIT_MODE_API = "api"
INIT_MODE_WORKER = "worker"

SCHEMA_LOCK_KEY = 8462751100339012
_SCHEMA_LOCK_TIMEOUT_S = 120.0
_SCHEMA_LOCK_POLL_S = 1.0
MIGRATION_STATE_KEY = "schema_migration"
MIGRATION_STATE_READY = "ready"
MIGRATION_STATE_MIGRATING = "migrating"
MIGRATION_STATE_FAILED = "failed"


# ---------------------------------------------------------------------------
# Lock helpers
# ---------------------------------------------------------------------------


@contextmanager
def _schema_lock() -> Iterator[None]:
    """Hold a session-level advisory lock for the whole init_db body.

    pg_advisory_xact_lock (used previously) was released when the caller's
    transaction committed, which freed the lock *before* Alembic ran. A
    session-level pg_advisory_lock on a dedicated connection keeps two
    concurrent init_db callers serialized across the Alembic upgrade too.

    The acquisition is bounded: pg_advisory_lock() ignores lock_timeout, so we
    poll pg_try_advisory_lock() with a deadline. If another instance is stuck
    mid-migration we fail fast instead of blocking startup forever.
    """
    conn = engine.connect()
    try:
        deadline = time.monotonic() + _SCHEMA_LOCK_TIMEOUT_S
        while True:
            acquired = bool(conn.exec_driver_sql(f"SELECT pg_try_advisory_lock({SCHEMA_LOCK_KEY})").scalar())
            conn.commit()
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out after {_SCHEMA_LOCK_TIMEOUT_S:.0f}s waiting for the schema advisory "
                    "lock; another instance may be stuck migrating."
                )
            time.sleep(_SCHEMA_LOCK_POLL_S)
        yield
    finally:
        try:
            conn.exec_driver_sql(f"SELECT pg_advisory_unlock({SCHEMA_LOCK_KEY})")
            conn.commit()
        except Exception:
            logger.exception("Failed to release schema advisory lock.")
        conn.close()


def _set_migration_state(conn: Connection, *, state: str, target_version: str) -> None:
    now = utcnow_naive()
    conn.execute(
        text(
            """
            INSERT INTO system_metadata (key, updated_at, last_ingestion, version)
            VALUES (:key, :updated_at, :last_ingestion, :version)
            ON CONFLICT(key) DO UPDATE SET
                updated_at = excluded.updated_at,
                last_ingestion = excluded.last_ingestion,
                version = excluded.version
            """
        ),
        {
            "key": MIGRATION_STATE_KEY,
            "updated_at": state,
            "last_ingestion": now,
            "version": target_version,
        },
    )


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


def get_migration_state() -> str:
    with engine.begin() as conn:
        inspector = inspect(conn)
        if not inspector.has_table("system_metadata"):
            return MIGRATION_STATE_READY
        row = conn.execute(
            text("SELECT updated_at FROM system_metadata WHERE key = :key"),
            {"key": MIGRATION_STATE_KEY},
        ).fetchone()
        if not row or not row[0]:
            return MIGRATION_STATE_READY
        return str(row[0])


# ---------------------------------------------------------------------------
# Wait helpers
# ---------------------------------------------------------------------------


def wait_for_migration_ready(*, timeout_s: float, interval_s: float = 1.0) -> bool:
    deadline = utcnow_naive() + timedelta(seconds=max(0.0, timeout_s))
    wait_seconds = max(interval_s, 0.1)
    logged_waiting = False
    while utcnow_naive() <= deadline:
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


# ---------------------------------------------------------------------------
# Init / migration
# ---------------------------------------------------------------------------


def _upsert_schema_version(conn: Connection, schema_version: str) -> None:
    now = utcnow_naive()
    existing_row = conn.execute(
        text("SELECT updated_at FROM system_metadata WHERE key = 'scryfall_data'")
    ).fetchone()
    existing_updated_at = ""
    if existing_row and existing_row[0]:
        existing_updated_at = str(existing_row[0])
    conn.execute(
        text(
            """
            INSERT INTO system_metadata (key, updated_at, last_ingestion, version)
            VALUES (:key, :updated_at, :last_ingestion, :version)
            ON CONFLICT(key) DO UPDATE SET
                updated_at = excluded.updated_at,
                last_ingestion = excluded.last_ingestion,
                version = excluded.version
            """
        ),
        {
            "key": SCRYFALL_DATA_KEY,
            "updated_at": existing_updated_at,
            "last_ingestion": now,
            "version": schema_version,
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
    logger.info("Running Alembic upgrade to head.")
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic upgrade complete.")


def init_db(mode: str = INIT_MODE_API) -> None:
    """
    Initialize DB schema.

    - Use Alembic migrations to reach schema head.
    - Keep advisory lock for concurrency safety.
    """
    if mode not in (INIT_MODE_API, INIT_MODE_WORKER):
        raise ValueError(f"Unsupported init_db mode: {mode}")
    logger.info("Initializing database...")

    with _schema_lock():
        try:
            # Migration STATE is written in both API and worker modes so the
            # `wait_for_migration_ready` gate works regardless of which process
            # runs the migration. (`_upsert_schema_version` tracks Scryfall data
            # and stays worker-only.)
            with engine.begin() as conn:
                inspector = inspect(conn)
                if inspector.has_table("system_metadata"):
                    _set_migration_state(conn, state=MIGRATION_STATE_MIGRATING, target_version=DB_SCHEMA_VERSION)
            _upgrade_schema_to_head()
            with engine.begin() as conn:
                if mode == INIT_MODE_WORKER:
                    _upsert_schema_version(conn, DB_SCHEMA_VERSION)
                _set_migration_state(conn, state=MIGRATION_STATE_READY, target_version=DB_SCHEMA_VERSION)
        except Exception:
            # Persist failed state in a separate transaction. If we wrote this inside the failed
            # transaction it would be rolled back alongside the original error.
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
