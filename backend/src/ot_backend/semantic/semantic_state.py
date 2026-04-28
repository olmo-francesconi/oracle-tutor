from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..core.models import SystemMetadata, _utcnow_naive

SEMANTIC_DATA_KEY = "semantic_data"
SEMANTIC_DATASET_EXPORT_KEY = "semantic_dataset_export"
SEMANTIC_ACTIVE_MODEL_KEY = "semantic_active_model"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _get_or_create_row(db: Session, key: str) -> SystemMetadata:
    row = _fetch_row(db, key)
    if row is not None:
        return row

    row = SystemMetadata(
        key=key,
        updated_at="",
        last_ingestion=_utcnow_naive(),
        version="0",
    )
    db.add(row)
    db.flush()
    return row


def _parse_int(value: str | None) -> int:
    try:
        return int(value or "0")
    except ValueError:
        return 0


def _fetch_row(db: Session, key: str) -> SystemMetadata | None:
    return db.get(SystemMetadata, key)


def get_semantic_data_version(db: Session) -> int:
    row = _fetch_row(db, SEMANTIC_DATA_KEY)
    if row is None:
        return 0
    return _parse_int(row.version)


def bump_semantic_data_version(db: Session) -> int:
    row = _get_or_create_row(db, SEMANTIC_DATA_KEY)
    next_version = _parse_int(row.version) + 1
    row.version = str(next_version)
    row.updated_at = _now_iso()
    row.last_ingestion = _utcnow_naive()
    db.commit()
    return next_version


def record_exported_dataset_version(db: Session, semantic_data_version: int) -> None:
    row = _get_or_create_row(db, SEMANTIC_DATASET_EXPORT_KEY)
    row.version = str(semantic_data_version)
    row.updated_at = _now_iso()
    row.last_ingestion = _utcnow_naive()
    db.commit()


def get_exported_dataset_version(db: Session) -> int:
    row = _fetch_row(db, SEMANTIC_DATASET_EXPORT_KEY)
    if row is None:
        return 0
    return _parse_int(row.version)


def record_active_model_data_version(db: Session, semantic_data_version: int) -> None:
    row = _get_or_create_row(db, SEMANTIC_ACTIVE_MODEL_KEY)
    row.version = str(semantic_data_version)
    row.updated_at = _now_iso()
    row.last_ingestion = _utcnow_naive()
    db.commit()


def get_active_model_data_version(db: Session) -> int:
    row = _fetch_row(db, SEMANTIC_ACTIVE_MODEL_KEY)
    if row is None:
        return 0
    return _parse_int(row.version)


def build_training_dataset_metadata(db: Session) -> dict[str, object]:
    return {
        "semantic_data_version": get_semantic_data_version(db),
        "exported_at": _now_iso(),
    }
