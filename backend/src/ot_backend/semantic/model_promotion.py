from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.database import SessionLocal
from ..core.models import CardFace, SemanticModel, SemanticModelEmbedding
from .model_registry import (
    SEMANTIC_MODEL_STATUS_ACTIVE,
    SEMANTIC_MODEL_STATUS_EMBEDDING,
    SEMANTIC_MODEL_STATUS_FAILED,
    SEMANTIC_MODEL_STATUS_READY,
    materialize_semantic_model,
)
from .semantic_state import get_semantic_data_version, record_active_model_data_version
from .text_prep import normalize_oracle_text
from .training_service import _load_sentence_transformer_class

logger = logging.getLogger("ot_backend.semantic.model_promotion")

_PROMOTION_ADVISORY_LOCK_KEY = 7391824650182736
_DEFAULT_REEMBED_BATCH_SIZE = 64
SEMANTIC_MODEL_CONFIG_DATASET_METADATA = "dataset_metadata"
SEMANTIC_MODEL_CONFIG_SOURCE_DATA_VERSION = "semantic_data_version"
_EMBEDDINGS_ARCHIVE_RELATIVE_PATH = Path("embeddings") / "embeddings.npz"


def _try_promotion_advisory_lock(db: Session) -> bool:
    return bool(db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _PROMOTION_ADVISORY_LOCK_KEY}))


def _claim_model_for_promotion(model_id: str) -> tuple[Path, Path]:
    """Validate + transition model to EMBEDDING status under the advisory lock.

    Runs all preconditions (existence, not-already-active, no other in-flight
    promotion, not stale) in one place so the long-running embed+activate phase
    can proceed without re-taking the lock.
    """
    with SessionLocal() as db:
        if not _try_promotion_advisory_lock(db):
            raise RuntimeError("Another semantic model promotion is already running.")

        model = db.get(SemanticModel, model_id)
        if model is None:
            raise KeyError(f"Semantic model {model_id} not found.")
        if model.is_active and model.status == SEMANTIC_MODEL_STATUS_ACTIVE:
            raise ValueError(f"Semantic model {model_id} is already active.")
        if model.status == SEMANTIC_MODEL_STATUS_EMBEDDING:
            raise RuntimeError(f"Semantic model {model_id} promotion is already in progress.")
        other_embedding = db.scalar(
            select(SemanticModel.id).where(
                SemanticModel.status == SEMANTIC_MODEL_STATUS_EMBEDDING,
                SemanticModel.id != model_id,
            ).limit(1)
        )
        if other_embedding is not None:
            raise RuntimeError(f"Another semantic model ({other_embedding}) promotion is already running.")
        _ensure_model_is_not_stale(db, model)

        model.status = SEMANTIC_MODEL_STATUS_EMBEDDING
        model.error_message = None
        merged_metrics = dict(model.metrics_json or {})
        merged_metrics["promotion_started_at"] = datetime.now(UTC).isoformat()
        model.metrics_json = merged_metrics
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise RuntimeError("Another semantic model promotion is already running.") from exc
        db.refresh(model)
        return materialize_semantic_model(model)


def promote_semantic_model(model_id: str, *, embed_batch_size: int = _DEFAULT_REEMBED_BATCH_SIZE) -> bool:
    """End-to-end promotion: claim, embed, activate.

    Returns True on success, False if the long-running embed/activate phase
    failed (model is marked failed in that case). Raises on pre-flight failures
    (missing / already-active / stale / lock contention) before the model is
    touched.
    """
    model_root, bundle_root = _claim_model_for_promotion(model_id)
    try:
        embedding_count, embedding_backend = _populate_model_embeddings(
            model_id,
            model_root,
            bundle_root,
            batch_size=embed_batch_size,
        )
        _activate_model(model_id, embedding_count=embedding_count, embedding_backend=embedding_backend)

        try:
            from .index import mark_semantic_index_stale

            mark_semantic_index_stale()
        except Exception:
            logger.exception("Failed to mark semantic index cache stale after activation.")
        return True
    except Exception as exc:
        logger.exception("Semantic model promotion failed for model_id=%s", model_id)
        _mark_model_failed(model_id, str(exc))
        _clear_model_embeddings(model_id)
        return False


def _iter_face_rows(batch_size: int) -> Iterator[list[tuple[str, int, str]]]:
    effective_batch_size = max(1, batch_size)
    with SessionLocal() as db:
        rows = db.execute(
            select(
                CardFace.oracle_id,
                CardFace.face_ix,
                CardFace.name,
                CardFace.type_line,
                CardFace.oracle_text,
            ).order_by(CardFace.oracle_id, CardFace.face_ix)
        )
        while True:
            chunk = rows.fetchmany(effective_batch_size)
            if not chunk:
                return
            yield [
                (
                    oracle_id,
                    face_ix,
                    normalize_oracle_text(text=oracle_text or "", card_name=name or "", type_line=type_line or ""),
                )
                for oracle_id, face_ix, name, type_line, oracle_text in chunk
            ]


def _resolve_embeddings_archive_path(bundle_root: Path) -> Path | None:
    candidate = bundle_root / _EMBEDDINGS_ARCHIVE_RELATIVE_PATH
    return candidate if candidate.exists() else None


def _resolve_pytorch_model_path(bundle_root: Path) -> Path | None:
    for candidate in (bundle_root / "models" / "pytorch", bundle_root / "pytorch"):
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _store_model_embeddings_batches(
    model_id: str,
    row_batches: Iterable[list[tuple[str, int, list[float]]]],
) -> int:
    """Replace all embeddings for `model_id` atomically.

    Staging-via-single-transaction: the old rows and all new batches sit in one
    transaction, so concurrent readers always see the pre-txn state until the
    final commit. A crash mid-population rolls back cleanly instead of leaving
    the model with partial embeddings.
    """
    total = 0
    with SessionLocal() as db:
        db.query(SemanticModelEmbedding).filter(SemanticModelEmbedding.model_id == model_id).delete()
        for rows in row_batches:
            if not rows:
                continue
            db.add_all(
                SemanticModelEmbedding(
                    model_id=model_id,
                    oracle_id=oracle_id,
                    face_ix=face_ix,
                    embedding=embedding,
                )
                for oracle_id, face_ix, embedding in rows
            )
            db.flush()
            total += len(rows)
        db.commit()
    return total


def _store_model_embeddings(model_id: str, rows: list[tuple[str, int, list[float]]]) -> int:
    return _store_model_embeddings_batches(model_id, [rows])


def _store_precomputed_embeddings_from_archive(model_id: str, archive_path: Path, *, batch_size: int) -> int:
    logger.info("Loading precomputed semantic embeddings from %s", archive_path)
    with np.load(archive_path, allow_pickle=False) as archive:
        oracle_ids = archive["oracle_ids"]
        face_ixs = archive["face_ixs"]
        embeddings = np.asarray(archive["embeddings"], dtype=np.float32)

        if len(oracle_ids) != len(face_ixs) or len(oracle_ids) != len(embeddings):
            raise RuntimeError(
                f"Precomputed embeddings archive {archive_path} has inconsistent lengths: "
                f"oracle_ids={len(oracle_ids)} face_ixs={len(face_ixs)} embeddings={len(embeddings)}."
            )

        def iter_batches() -> Iterator[list[tuple[str, int, list[float]]]]:
            step = max(1, batch_size)
            for start in range(0, len(oracle_ids), step):
                end = min(start + step, len(oracle_ids))
                yield [
                    (
                        str(oracle_ids[idx]),
                        int(face_ixs[idx]),
                        np.asarray(embeddings[idx], dtype=np.float32).tolist(),
                    )
                    for idx in range(start, end)
                ]

        count = _store_model_embeddings_batches(model_id, iter_batches())
        logger.info("Loaded precomputed embeddings. faces=%d", count)
        return count


def _compute_and_store_embeddings_from_pytorch_model(model_id: str, model_path: Path, *, batch_size: int) -> int:
    SentenceTransformer = _load_sentence_transformer_class()
    logger.info("Computing semantic embeddings with PyTorch model at %s (batch_size=%d)", model_path, batch_size)
    model = SentenceTransformer(str(model_path), local_files_only=True)

    def iter_batches() -> Iterator[list[tuple[str, int, list[float]]]]:
        for face_rows in _iter_face_rows(batch_size):
            texts = [text for _, _, text in face_rows]
            vectors = np.asarray(
                model.encode(
                    texts,
                    batch_size=max(1, batch_size),
                    normalize_embeddings=True,
                    show_progress_bar=False,
                ),
                dtype=np.float32,
            )
            yield [
                (
                    oracle_id,
                    face_ix,
                    np.asarray(vectors[idx], dtype=np.float32).tolist(),
                )
                for idx, (oracle_id, face_ix, _text) in enumerate(face_rows)
            ]

    count = _store_model_embeddings_batches(model_id, iter_batches())
    logger.info("PyTorch embedding complete. faces=%d", count)
    return count


def _compute_and_store_embeddings_from_onnx_model(model_id: str, model_root: Path, *, batch_size: int) -> int:
    from .index import OnnxTextEncoder

    logger.info("Computing semantic embeddings with ONNX model at %s (batch_size=%d)", model_root, batch_size)
    encoder = OnnxTextEncoder(model_root=model_root)

    def iter_batches() -> Iterator[list[tuple[str, int, list[float]]]]:
        for face_rows in _iter_face_rows(batch_size):
            texts = [text for _, _, text in face_rows]
            vectors = encoder.encode_many(texts, batch_size=max(1, batch_size), normalize_inputs=False)
            yield [
                (oracle_id, face_ix, vectors[idx])
                for idx, (oracle_id, face_ix, _text) in enumerate(face_rows)
            ]

    count = _store_model_embeddings_batches(model_id, iter_batches())
    logger.info("ONNX embedding complete. faces=%d", count)
    return count


def _populate_model_embeddings(model_id: str, model_root: Path, bundle_root: Path, *, batch_size: int) -> tuple[int, str]:
    archive_path = _resolve_embeddings_archive_path(bundle_root)
    if archive_path is not None:
        return _store_precomputed_embeddings_from_archive(model_id, archive_path, batch_size=batch_size), "precomputed"

    pytorch_model_path = _resolve_pytorch_model_path(bundle_root)
    if pytorch_model_path is not None:
        return (
            _compute_and_store_embeddings_from_pytorch_model(
                model_id,
                pytorch_model_path,
                batch_size=batch_size,
            ),
            "pytorch",
        )

    return _compute_and_store_embeddings_from_onnx_model(model_id, model_root, batch_size=batch_size), "onnx"


def _activate_model(model_id: str, *, embedding_count: int, embedding_backend: str | None = None) -> None:
    activated_at = datetime.now(UTC).replace(tzinfo=None)
    with SessionLocal() as db:
        db.query(SemanticModel).filter(SemanticModel.is_active.is_(True), SemanticModel.id != model_id).update(
            {
                SemanticModel.is_active: False,
                SemanticModel.status: SEMANTIC_MODEL_STATUS_READY,
            },
            synchronize_session=False,
        )
        model = db.get(SemanticModel, model_id)
        if model is None:
            raise KeyError(f"Semantic model {model_id} not found during activation.")

        merged_metrics = dict(model.metrics_json or {})
        merged_metrics["embedding_count"] = embedding_count
        merged_metrics["promotion_completed_at"] = datetime.now(UTC).isoformat()
        if embedding_backend is not None:
            merged_metrics["promotion_embedding_backend"] = embedding_backend

        model.status = SEMANTIC_MODEL_STATUS_ACTIVE
        model.is_active = True
        model.activated_at = activated_at
        model.error_message = None
        model.metrics_json = merged_metrics
        db.commit()
        semantic_data_version = _get_model_source_data_version(model)
        if semantic_data_version is not None:
            record_active_model_data_version(db, semantic_data_version)


def _mark_model_failed(model_id: str, error_message: str) -> None:
    with SessionLocal() as db:
        model = db.get(SemanticModel, model_id)
        if model is None:
            return
        model.status = SEMANTIC_MODEL_STATUS_FAILED
        model.error_message = error_message[:4000]
        model.is_active = False
        db.commit()


def _clear_model_embeddings(model_id: str) -> None:
    with SessionLocal() as db:
        db.query(SemanticModelEmbedding).filter(SemanticModelEmbedding.model_id == model_id).delete()
        db.commit()


def _get_model_source_data_version(model: SemanticModel) -> int | None:
    config = model.config_json or {}
    raw_value = config.get(SEMANTIC_MODEL_CONFIG_SOURCE_DATA_VERSION)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str) and raw_value.isdigit():
        return int(raw_value)

    dataset_metadata = config.get(SEMANTIC_MODEL_CONFIG_DATASET_METADATA)
    if isinstance(dataset_metadata, dict):
        fallback = dataset_metadata.get(SEMANTIC_MODEL_CONFIG_SOURCE_DATA_VERSION)
        if isinstance(fallback, int):
            return fallback
        if isinstance(fallback, str) and fallback.isdigit():
            return int(fallback)
    return None


def _ensure_model_is_not_stale(db: Session, model: SemanticModel) -> None:
    source_version = _get_model_source_data_version(model)
    current_version = get_semantic_data_version(db)

    if source_version is None and current_version == 0:
        return
    if source_version is None:
        raise RuntimeError(
            f"Semantic model {model.id} has no source semantic data version recorded. "
            "Promotion blocked to prevent promoting against stale data."
        )

    if current_version and current_version != source_version:
        raise RuntimeError(
            f"Semantic model {model.id} is stale: source semantic data version {source_version} "
            f"does not match current version {current_version}."
        )
