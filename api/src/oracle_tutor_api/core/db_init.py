from __future__ import annotations

import logging

from sqlalchemy import inspect, text

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

        # If an old schema exists with a removed column, the safest/simple approach is to drop and rebuild.
        # We only do this automatically on Postgres.
        if dialect == "postgresql":
            inspector = inspect(conn)
            if inspector.has_table("card_faces"):
                cols = {c["name"] for c in inspector.get_columns("card_faces")}
                if "embedding" in cols:
                    logger.warning("Old schema detected (embedding column). Dropping tables to rebuild...")
                    conn.execute(text("DROP TABLE IF EXISTS card_faces CASCADE"))
                    conn.execute(text("DROP TABLE IF EXISTS cards CASCADE"))
                    conn.execute(text("DROP TABLE IF EXISTS system_metadata CASCADE"))
                    conn.execute(text("DROP TABLE IF EXISTS ingestion_logs CASCADE"))

        Base.metadata.create_all(conn)

        if dialect == "postgresql":
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cards_name_trgm ON cards USING gin (name gin_trgm_ops)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_card_faces_name_trgm ON card_faces USING gin (name gin_trgm_ops)"))

    logger.info("Database initialized.")


