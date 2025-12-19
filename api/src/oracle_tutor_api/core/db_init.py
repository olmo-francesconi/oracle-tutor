from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from .config import DB_SCHEMA_VERSION, parse_version
from .database import engine
from .models import Base

logger = logging.getLogger("oracle_tutor_api.data")


def init_db() -> None:
    """
    Initialize DB schema.

    - Postgres: enable pg_trgm and create trigram indexes.
    - Other DBs (tests): just create tables.
    """
    logger.info("Initializing database...")

    with engine.begin() as conn:
        dialect = conn.dialect.name

        if dialect == "postgresql":
            # Ensure trigram extension for fuzzy search (name suggestions).
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

        # Check if we need to reset cards/faces due to schema version mismatch
        should_reset_cards = False
        inspector = inspect(conn)

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

        if should_reset_cards:
            logger.info("Dropping card tables for rebuild...")
            if dialect == "postgresql":
                conn.execute(text("DROP TABLE IF EXISTS card_faces CASCADE"))
                conn.execute(text("DROP TABLE IF EXISTS cards CASCADE"))
            else:
                # SQLite doesn't support CASCADE in DROP TABLE, but we'll try to drop in order
                conn.execute(text("DROP TABLE IF EXISTS card_faces"))
                conn.execute(text("DROP TABLE IF EXISTS cards"))

        Base.metadata.create_all(conn)

        if dialect == "postgresql":
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cards_name_trgm ON cards USING gin (name gin_trgm_ops)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_card_faces_name_trgm ON card_faces USING gin (name gin_trgm_ops)"))

    logger.info("Database initialized.")


