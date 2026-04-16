from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from ot_backend.core.config import DB_SCHEMA_VERSION
from ot_backend.core.database import SessionLocal
from ot_backend.core.db_init import (
    INIT_MODE_API,
    INIT_MODE_WORKER,
    MIGRATION_STATE_KEY,
    MIGRATION_STATE_READY,
    init_db,
    wait_for_migration_ready,
)
from ot_backend.core.models import Card, CardFace, CardRaw, SystemMetadata


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _clean_db() -> None:
    with SessionLocal() as db:
        db.query(CardFace).delete()
        db.query(Card).delete()
        db.query(CardRaw).delete()
        db.query(SystemMetadata).delete()
        db.commit()


def _seed_card_and_old_schema() -> None:
    with SessionLocal() as db:
        db.add(
            CardRaw(
                id="scryfall-card-reset-check",
                oracle_id="card-reset-check",
                name="Reset Check Card",
                lang="en",
                layout="normal",
                color_identity=["U"],
                keywords=[],
                legalities={},
                rarity="common",
                set_code="tst",
                set_id="set-tst",
                set_name="Test Set",
                set_type="expansion",
                collector_number="1",
                games=["paper"],
                finishes=["nonfoil"],
            )
        )
        db.add(
            Card(
                oracle_id="card-reset-check",
                scryfall_id="scryfall-card-reset-check",
                name="Reset Check Card",
                layout="normal",
                rarity="common",
                legalities={},
                color_identity=["U"],
            )
        )
        db.add(
            SystemMetadata(
                key="scryfall_data",
                updated_at="2026-01-01T00:00:00Z",
                last_ingestion=_utcnow_naive(),
                version="1.0.0",
            )
        )
        db.commit()


def test_api_mode_does_not_drop_cards_when_schema_is_old() -> None:
    init_db(mode=INIT_MODE_API)
    _clean_db()
    _seed_card_and_old_schema()

    init_db(mode=INIT_MODE_API)

    with SessionLocal() as db:
        count = db.query(Card).count()
        assert count == 1


def test_worker_mode_sets_schema_metadata_and_ready_state() -> None:
    init_db(mode=INIT_MODE_API)
    _clean_db()
    _seed_card_and_old_schema()

    init_db(mode=INIT_MODE_WORKER)

    with SessionLocal() as db:
        meta = db.get(SystemMetadata, "scryfall_data")
        assert meta is not None
        assert meta.version == DB_SCHEMA_VERSION
        migration_meta = db.get(SystemMetadata, MIGRATION_STATE_KEY)
        assert migration_meta is not None
        assert migration_meta.updated_at == MIGRATION_STATE_READY


def test_wait_for_migration_ready_times_out_when_stuck_migrating() -> None:
    init_db(mode=INIT_MODE_API)
    _clean_db()

    with SessionLocal() as db:
        db.execute(
            text(
                """
                INSERT INTO system_metadata (key, updated_at, last_ingestion, version)
                VALUES (:key, :updated_at, :last_ingestion, :version)
                """
            ),
            {
                "key": MIGRATION_STATE_KEY,
                "updated_at": "migrating",
                "last_ingestion": _utcnow_naive(),
                "version": DB_SCHEMA_VERSION,
            },
        )
        db.commit()

    ready = wait_for_migration_ready(timeout_s=0.05, interval_s=0.01)
    assert ready is False

    # Clean up stale "migrating" state so it doesn't leak to subsequent tests
    _clean_db()
