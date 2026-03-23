from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import inspect, text

from .config import ALLOW_SCHEMA_RESET, DB_SCHEMA_VERSION, parse_version
from .database import engine
from .models import Base

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
    while _utcnow_naive() <= deadline:
        state = get_migration_state()
        if state == MIGRATION_STATE_READY:
            return True
        if state == MIGRATION_STATE_FAILED:
            return False
        time.sleep(wait_seconds)
    return get_migration_state() == MIGRATION_STATE_READY


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


def _ensure_postgres_features(conn, dialect: str) -> None:
    if dialect == "postgresql":
        # Ensure trigram extension for fuzzy search (name suggestions).
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


def _ensure_indexes(conn, dialect: str) -> None:
    if dialect == "postgresql":
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cards_name_trgm ON cards USING gin (name gin_trgm_ops)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_card_faces_name_trgm ON card_faces USING gin (name gin_trgm_ops)"))


def _should_reset_cards(conn) -> bool:
    should_reset_cards = False
    inspector = inspect(conn)

    if inspector.has_table("cards"):
        cols = {c["name"] for c in inspector.get_columns("cards")}
        required_cols = {"scryfall_set", "collector_number"}
        if not required_cols.issubset(cols):
            logger.warning("Legacy schema detected (missing printing metadata columns).")
            should_reset_cards = True

    if inspector.has_table("card_faces"):
        # Legacy check: if 'embedding' exists, it's definitely an old schema that needs reset
        cols = {c["name"] for c in inspector.get_columns("card_faces")}
        if "embedding" in cols:
            logger.warning("Legacy schema detected (embedding column).")
            should_reset_cards = True

    if not should_reset_cards and inspector.has_table("system_metadata"):
        try:
            # Get current DB version
            res = conn.execute(
                text("SELECT schema_version FROM system_metadata WHERE key = 'scryfall_data'")
            ).fetchone()
            if res:
                db_version = res[0]
                # We only force a full table reset on Major or Minor version changes.
                # Patches (the 3rd digit) should ideally be compatible or handled by Alembic/manual SQL.
                # Since we don't have migrations yet, we'll reset on any Major/Minor change.
                v_db = parse_version(db_version)
                v_app = parse_version(DB_SCHEMA_VERSION)
                if v_db[0] < v_app[0] or v_db[1] < v_app[1]:
                    logger.warning(
                        f"Schema version mismatch: DB={db_version}, App={DB_SCHEMA_VERSION}. "
                        "Resetting card tables."
                    )
                    should_reset_cards = True
        except Exception as e:
            logger.warning(f"Could not check schema version: {e}. Defaulting to safe state.")

    return should_reset_cards


def _drop_card_tables(conn, dialect: str) -> None:
    logger.info("Dropping card tables for rebuild...")
    if dialect == "postgresql":
        conn.execute(text("DROP TABLE IF EXISTS card_face_semantic_embeddings CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS card_relationships CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS tag_ancestor_map CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS card_taggings CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS card_tag_map CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS tags CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS card_tags CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS card_faces CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS cards CASCADE"))
    else:
        # SQLite doesn't support CASCADE in DROP TABLE, but we'll try to drop in order
        conn.execute(text("DROP TABLE IF EXISTS card_face_semantic_embeddings"))
        conn.execute(text("DROP TABLE IF EXISTS card_relationships"))
        conn.execute(text("DROP TABLE IF EXISTS tag_ancestor_map"))
        conn.execute(text("DROP TABLE IF EXISTS card_taggings"))
        conn.execute(text("DROP TABLE IF EXISTS card_tag_map"))
        conn.execute(text("DROP TABLE IF EXISTS tags"))
        conn.execute(text("DROP TABLE IF EXISTS card_tags"))
        conn.execute(text("DROP TABLE IF EXISTS card_faces"))
        conn.execute(text("DROP TABLE IF EXISTS cards"))


def init_db(mode: str = INIT_MODE_API) -> None:
    """
    Initialize DB schema.

    - Postgres: enable pg_trgm and create trigram indexes.
    - Other DBs (tests): just create tables.
    """
    if mode not in (INIT_MODE_API, INIT_MODE_WORKER):
        raise ValueError(f"Unsupported init_db mode: {mode}")
    logger.info("Initializing database...")

    try:
        with engine.begin() as conn:
            dialect = conn.dialect.name
            _acquire_schema_lock(conn, dialect)
            _ensure_postgres_features(conn, dialect)

            Base.metadata.create_all(conn)
            _ensure_indexes(conn, dialect)

            if mode == INIT_MODE_WORKER:
                _set_migration_state(conn, state=MIGRATION_STATE_MIGRATING, target_version=DB_SCHEMA_VERSION)
                should_reset_cards = _should_reset_cards(conn)

                if should_reset_cards:
                    if not ALLOW_SCHEMA_RESET:
                        raise RuntimeError(
                            "Schema reset required but disabled. Set ORACLE_TUTOR_API_ALLOW_SCHEMA_RESET=true "
                            "to allow destructive card table reset."
                        )
                    _drop_card_tables(conn, dialect)

                Base.metadata.create_all(conn)
                _ensure_indexes(conn, dialect)
                _upsert_schema_version(conn, DB_SCHEMA_VERSION)
                _set_migration_state(conn, state=MIGRATION_STATE_READY, target_version=DB_SCHEMA_VERSION)
    except Exception:
        # Persist failed state in a separate transaction. If we wrote this inside the failed
        # transaction it would be rolled back alongside the original error.
        if mode == INIT_MODE_WORKER:
            try:
                with engine.begin() as fail_conn:
                    Base.metadata.create_all(fail_conn)
                    _set_migration_state(
                        fail_conn,
                        state=MIGRATION_STATE_FAILED,
                        target_version=DB_SCHEMA_VERSION,
                    )
            except Exception:
                logger.exception("Failed to persist schema migration failed state.")
        raise

    logger.info("Database initialized (mode=%s).", mode)
