from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from oracle_tutor_api.core.config import DB_SCHEMA_VERSION
from oracle_tutor_api.core.database import SessionLocal
from oracle_tutor_api.core.db_init import (
    INIT_MODE_API,
    INIT_MODE_WORKER,
    MIGRATION_STATE_FAILED,
    MIGRATION_STATE_KEY,
    MIGRATION_STATE_READY,
    get_migration_state,
    init_db,
    wait_for_migration_ready,
)
from oracle_tutor_api.core.models import Card, CardFace, SystemMetadata


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _clean_db() -> None:
    with SessionLocal() as db:
        db.query(CardFace).delete()
        db.query(Card).delete()
        db.query(SystemMetadata).delete()
        db.commit()


def _seed_card_and_old_schema() -> None:
    with SessionLocal() as db:
        db.add(
            Card(
                id="card-reset-check",
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
                data_updated_at="2026-01-01T00:00:00Z",
                last_ingestion=_utcnow_naive(),
                schema_version="1.0.0",
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


def test_worker_mode_refuses_destructive_reset_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    init_db(mode=INIT_MODE_API)
    _clean_db()
    _seed_card_and_old_schema()

    monkeypatch.setattr("oracle_tutor_api.core.db_init.ALLOW_SCHEMA_RESET", False)

    with pytest.raises(RuntimeError, match="Schema reset required but disabled"):
        init_db(mode=INIT_MODE_WORKER)

    assert get_migration_state() == MIGRATION_STATE_FAILED


def test_worker_mode_resets_cards_and_sets_ready_state(monkeypatch: pytest.MonkeyPatch) -> None:
    init_db(mode=INIT_MODE_API)
    _clean_db()
    _seed_card_and_old_schema()

    monkeypatch.setattr("oracle_tutor_api.core.db_init.ALLOW_SCHEMA_RESET", True)
    init_db(mode=INIT_MODE_WORKER)

    with SessionLocal() as db:
        assert db.query(Card).count() == 0
        meta = db.get(SystemMetadata, "scryfall_data")
        assert meta is not None
        assert meta.schema_version == DB_SCHEMA_VERSION
        migration_meta = db.get(SystemMetadata, MIGRATION_STATE_KEY)
        assert migration_meta is not None
        assert migration_meta.data_updated_at == MIGRATION_STATE_READY


def test_wait_for_migration_ready_times_out_when_stuck_migrating() -> None:
    init_db(mode=INIT_MODE_API)
    _clean_db()

    with SessionLocal() as db:
        db.execute(
            text(
                """
                INSERT INTO system_metadata (key, data_updated_at, last_ingestion, schema_version)
                VALUES (:key, :data_updated_at, :last_ingestion, :schema_version)
                """
            ),
            {
                "key": MIGRATION_STATE_KEY,
                "data_updated_at": "migrating",
                "last_ingestion": _utcnow_naive(),
                "schema_version": DB_SCHEMA_VERSION,
            },
        )
        db.commit()

    ready = wait_for_migration_ready(timeout_s=0.05, interval_s=0.01)
    assert ready is False

