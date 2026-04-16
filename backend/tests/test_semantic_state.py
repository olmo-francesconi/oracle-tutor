from __future__ import annotations

from ot_backend.core.database import SessionLocal
from ot_backend.core.db_init import init_db
from ot_backend.core.models import SystemMetadata
from ot_backend.semantic.semantic_state import (
    build_training_dataset_metadata,
    bump_semantic_data_version,
    get_active_model_data_version,
    get_exported_dataset_version,
    get_semantic_data_version,
    record_active_model_data_version,
    record_exported_dataset_version,
)


def _reset_semantic_metadata() -> None:
    init_db()
    with SessionLocal() as db:
        for key in ("semantic_data", "semantic_dataset_export", "semantic_active_model"):
            row = db.get(SystemMetadata, key)
            if row is not None:
                db.delete(row)
        db.commit()


def test_semantic_state_round_trips_versions() -> None:
    _reset_semantic_metadata()

    with SessionLocal() as db:
        assert get_semantic_data_version(db) == 0
        version = bump_semantic_data_version(db)
        assert version == 1
        assert get_semantic_data_version(db) == 1

    with SessionLocal() as db:
        record_exported_dataset_version(db, 1)
        record_active_model_data_version(db, 1)
        assert get_exported_dataset_version(db) == 1
        assert get_active_model_data_version(db) == 1


def test_build_training_dataset_metadata_uses_semantic_version() -> None:
    _reset_semantic_metadata()

    with SessionLocal() as db:
        bump_semantic_data_version(db)

    with SessionLocal() as db:
        metadata = build_training_dataset_metadata(db)

    assert metadata["semantic_data_version"] == 1
    assert "exported_at" in metadata
