from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.database import SessionLocal
from ..core.models import CardFaceAbility, SemanticAbilityEmbedding, SemanticModel
from .model_registry import (
    SEMANTIC_MODEL_STATUS_ACTIVE,
    SEMANTIC_MODEL_STATUS_EMBEDDING,
    SEMANTIC_MODEL_STATUS_FAILED,
    SEMANTIC_MODEL_STATUS_READY,
    get_active_semantic_model_id,
    materialize_semantic_model,
)
from .semantic_state import get_semantic_data_version, record_active_model_data_version
from .training_service import load_sentence_transformer_class

logger = logging.getLogger("ot_backend.semantic.model_promotion")

_PROMOTION_ADVISORY_LOCK_KEY = 7391824650182736
_DEFAULT_REEMBED_BATCH_SIZE = 64
SEMANTIC_MODEL_CONFIG_DATASET_METADATA = "dataset_metadata"
SEMANTIC_MODEL_CONFIG_SOURCE_DATA_VERSION = "semantic_data_version"
_EMBEDDINGS_ARCHIVE_RELATIVE_PATH = Path("embeddings") / "embeddings.npz"


def _acquire_promotion_lock(db: Session) -> bool:
    """Take a session-scoped advisory lock held for the whole promotion.

    Unlike a transaction-scoped lock, this is NOT released when intermediate
    transactions commit — it is held on this connection until explicitly
    unlocked (see `_release_promotion_lock`), so the entire claim → embed →
    activate sequence runs mutually exclusive with any other promotion.
    """
    acquired = bool(db.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": _PROMOTION_ADVISORY_LOCK_KEY}))
    # Session-level locks survive commit; commit so the lock connection isn't
    # left idle-in-transaction for the whole (potentially multi-minute) embed.
    db.commit()
    return acquired


def _release_promotion_lock(db: Session) -> None:
    db.scalar(text("SELECT pg_advisory_unlock(:key)"), {"key": _PROMOTION_ADVISORY_LOCK_KEY})
    db.commit()


def _claim_model_for_promotion(model_id: str) -> tuple[Path, Path]:
    """Validate + transition the model to EMBEDDING status.

    Runs all preconditions (existence, not-already-active, no other in-flight
    promotion, not stale) in one place. The caller must already hold the
    session-level promotion lock for the duration of the promotion.
    """
    with SessionLocal() as db:
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

    A session-level advisory lock is held on a dedicated connection for the
    entire claim → embed → activate sequence, so two promotions can never
    interleave (the second fails fast on lock contention).
    """
    with SessionLocal() as lock_db:
        if not _acquire_promotion_lock(lock_db):
            raise RuntimeError("Another semantic model promotion is already running.")
        try:
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
        finally:
            _release_promotion_lock(lock_db)



def count_missing_ability_embeddings(db: Session, model_id: str) -> int:
    """Distinct ability texts with no vector for `model_id`.

    Cheap enough to call on every ingest: one indexed anti-join.
    """
    missing = (
        select(CardFaceAbility.text_hash)
        .outerjoin(
            SemanticAbilityEmbedding,
            and_(
                SemanticAbilityEmbedding.text_hash == CardFaceAbility.text_hash,
                SemanticAbilityEmbedding.model_id == model_id,
            ),
        )
        .where(SemanticAbilityEmbedding.text_hash.is_(None))
        .group_by(CardFaceAbility.text_hash)
        .subquery()
    )
    return int(db.scalar(select(func.count()).select_from(missing)) or 0)


def _iter_missing_ability_rows(model_id: str, batch_size: int) -> Iterator[list[tuple[str, str]]]:
    effective = max(1, batch_size)
    with SessionLocal() as db:
        rows = db.execute(
            select(CardFaceAbility.text_hash, func.min(CardFaceAbility.normalized_text))
            .outerjoin(
                SemanticAbilityEmbedding,
                and_(
                    SemanticAbilityEmbedding.text_hash == CardFaceAbility.text_hash,
                    SemanticAbilityEmbedding.model_id == model_id,
                ),
            )
            .where(SemanticAbilityEmbedding.text_hash.is_(None))
            .group_by(CardFaceAbility.text_hash)
            .order_by(CardFaceAbility.text_hash)
        )
        while True:
            chunk = rows.fetchmany(effective)
            if not chunk:
                return
            yield [(text_hash, normalized_text) for text_hash, normalized_text in chunk]


def topup_active_model_embeddings(*, batch_size: int = _DEFAULT_REEMBED_BATCH_SIZE) -> int:
    """Embed ability texts the active model has no vector for.

    Ingest creates `card_face_abilities` rows but never embeds them — only
    promotion does, and it rewrites all ~37k. So a card printed with genuinely
    new wording is absent from the index until the next promotion, and a face
    whose abilities are ALL new cannot be retrieved at any threshold.

    This adds only what is missing, leaving existing vectors untouched. It is a
    no-op — and importantly, does not download the model bundle — when nothing
    is missing, which is the usual case.
    """
    with SessionLocal() as db:
        model_id = get_active_semantic_model_id(db)
        if model_id is None:
            logger.info("No active semantic model; skipping embedding top-up.")
            return 0
        missing = count_missing_ability_embeddings(db, model_id)

    if missing == 0:
        logger.info("Embedding top-up not needed; every ability text is covered.")
        return 0

    logger.info("Embedding top-up starting. model_id=%s missing_texts=%d", model_id, missing)
    lock_session = SessionLocal()
    try:
        if not _acquire_promotion_lock(lock_session):
            # A promotion is running and is about to rewrite everything anyway.
            logger.warning("Promotion in progress; skipping embedding top-up.")
            return 0
        try:
            model = None
            with SessionLocal() as db:
                model = db.get(SemanticModel, model_id)
            if model is None:
                return 0
            model_root, _bundle_root = materialize_semantic_model(model)

            from .index import OnnxTextEncoder

            encoder = OnnxTextEncoder(model_root=model_root)

            def iter_batches() -> Iterator[list[tuple[str, list[float]]]]:
                for ability_rows in _iter_missing_ability_rows(model_id, batch_size):
                    texts = [text for _hash, text in ability_rows]
                    vectors = encoder.encode_many(
                        texts, batch_size=max(1, batch_size), normalize_inputs=False
                    )
                    yield [(h, vectors[i]) for i, (h, _t) in enumerate(ability_rows)]

            stored = _append_model_embeddings_batches(model_id, iter_batches())
            logger.info("Embedding top-up complete. model_id=%s added=%d", model_id, stored)
            try:
                from .index import mark_semantic_index_stale

                mark_semantic_index_stale()
            except Exception:  # noqa: BLE001 — cache hint only
                logger.debug("Could not mark the semantic index stale after top-up.")
            return stored
        finally:
            _release_promotion_lock(lock_session)
    finally:
        lock_session.close()


def _iter_ability_rows(batch_size: int) -> Iterator[list[tuple[str, str]]]:
    """Yield batches of (text_hash, normalized_text) for every DISTINCT ability.

    Deduplicating here is the whole point of hashing ability text: ~63k ability
    instances collapse to ~37k distinct texts, so each one is encoded once and
    shared by every face that has it.
    """
    effective_batch_size = max(1, batch_size)
    with SessionLocal() as db:
        rows = db.execute(
            select(
                CardFaceAbility.text_hash,
                func.min(CardFaceAbility.normalized_text),
            )
            .group_by(CardFaceAbility.text_hash)
            .order_by(CardFaceAbility.text_hash)
        )
        while True:
            chunk = rows.fetchmany(effective_batch_size)
            if not chunk:
                return
            yield [(text_hash, normalized_text) for text_hash, normalized_text in chunk]


def _resolve_embeddings_archive_path(bundle_root: Path) -> Path | None:
    candidate = bundle_root / _EMBEDDINGS_ARCHIVE_RELATIVE_PATH
    return candidate if candidate.exists() else None


def _resolve_pytorch_model_path(bundle_root: Path) -> Path | None:
    for candidate in (bundle_root / "models" / "pytorch", bundle_root / "pytorch"):
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


class _MissingTorchError(RuntimeError):
    """The PyTorch embedding backend isn't installed in this environment."""


def _append_model_embeddings_batches(
    model_id: str,
    row_batches: Iterable[list[tuple[str, list[float]]]],
) -> int:
    """Add ability embeddings for `model_id` WITHOUT touching existing rows.

    Distinct from `_store_model_embeddings_batches`, which replaces the whole
    set for a promotion. The top-up must never delete: reusing the replacing
    variant wiped every vector and rewrote only the delta, so coverage went
    *down* on each run.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    total = 0
    with SessionLocal() as db:
        for rows in row_batches:
            if not rows:
                continue
            stmt = pg_insert(SemanticAbilityEmbedding).values(
                [
                    {"model_id": model_id, "text_hash": text_hash, "embedding": embedding}
                    for text_hash, embedding in rows
                ]
            )
            # A concurrent promotion may have inserted the same text already.
            db.execute(stmt.on_conflict_do_nothing(index_elements=["model_id", "text_hash"]))
            total += len(rows)
        db.commit()
    return total


def _store_model_embeddings_batches(
    model_id: str,
    row_batches: Iterable[list[tuple[str, list[float]]]],
) -> int:
    """Replace all ability embeddings for `model_id` atomically.

    Staging-via-single-transaction: the old rows and all new batches sit in one
    transaction, so concurrent readers always see the pre-txn state until the
    final commit. A crash mid-population rolls back cleanly instead of leaving
    the model with partial embeddings.
    """
    total = 0
    with SessionLocal() as db:
        db.query(SemanticAbilityEmbedding).filter(SemanticAbilityEmbedding.model_id == model_id).delete()
        for rows in row_batches:
            if not rows:
                continue
            db.add_all(
                SemanticAbilityEmbedding(
                    model_id=model_id,
                    text_hash=text_hash,
                    embedding=embedding,
                )
                for text_hash, embedding in rows
            )
            db.flush()
            total += len(rows)
        db.commit()
    return total


def store_model_embeddings(model_id: str, rows: list[tuple[str, list[float]]]) -> int:
    return _store_model_embeddings_batches(model_id, [rows])


def _store_precomputed_embeddings_from_archive(
    model_id: str, archive_path: Path, *, batch_size: int
) -> int | None:
    """Load ability vectors from a bundle's precomputed archive.

    Returns None when the archive predates the ability layer, signalling the
    caller to recompute from the bundled model weights.
    """
    logger.info("Loading precomputed semantic embeddings from %s", archive_path)
    with np.load(archive_path, allow_pickle=False) as archive:
        if "text_hashes" not in archive:
            # Legacy face-granular bundle (oracle_ids/face_ixs). Not usable for
            # ability search; the caller recomputes from the bundled model
            # weights instead of failing the promotion.
            logger.warning(
                "Ignoring face-granular precomputed archive %s; recomputing at ability granularity.",
                archive_path,
            )
            return None
        text_hashes = archive["text_hashes"]
        embeddings = np.asarray(archive["embeddings"], dtype=np.float32)

        if len(text_hashes) != len(embeddings):
            raise RuntimeError(
                f"Precomputed embeddings archive {archive_path} has inconsistent lengths: "
                f"text_hashes={len(text_hashes)} embeddings={len(embeddings)}."
            )

        def iter_batches() -> Iterator[list[tuple[str, list[float]]]]:
            step = max(1, batch_size)
            for start in range(0, len(text_hashes), step):
                end = min(start + step, len(text_hashes))
                yield [
                    (
                        str(text_hashes[idx]),
                        np.asarray(embeddings[idx], dtype=np.float32).tolist(),
                    )
                    for idx in range(start, end)
                ]

        count = _store_model_embeddings_batches(model_id, iter_batches())
        logger.info("Loaded precomputed embeddings. abilities=%d", count)
        return count


def _compute_and_store_embeddings_from_pytorch_model(model_id: str, model_path: Path, *, batch_size: int) -> int:
    try:
        SentenceTransformer = load_sentence_transformer_class()
    except Exception as exc:
        raise _MissingTorchError(str(exc)) from exc
    logger.info("Computing semantic embeddings with PyTorch model at %s (batch_size=%d)", model_path, batch_size)
    model = SentenceTransformer(str(model_path), local_files_only=True)

    def iter_batches() -> Iterator[list[tuple[str, list[float]]]]:
        for ability_rows in _iter_ability_rows(batch_size):
            texts = [text for _, text in ability_rows]
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
                (text_hash, np.asarray(vectors[idx], dtype=np.float32).tolist())
                for idx, (text_hash, _text) in enumerate(ability_rows)
            ]

    count = _store_model_embeddings_batches(model_id, iter_batches())
    logger.info("PyTorch embedding complete. abilities=%d", count)
    return count


def _compute_and_store_embeddings_from_onnx_model(model_id: str, model_root: Path, *, batch_size: int) -> int:
    from .index import OnnxTextEncoder

    logger.info("Computing semantic embeddings with ONNX model at %s (batch_size=%d)", model_root, batch_size)
    encoder = OnnxTextEncoder(model_root=model_root)

    def iter_batches() -> Iterator[list[tuple[str, list[float]]]]:
        for ability_rows in _iter_ability_rows(batch_size):
            texts = [text for _, text in ability_rows]
            vectors = encoder.encode_many(texts, batch_size=max(1, batch_size), normalize_inputs=False)
            yield [(text_hash, vectors[idx]) for idx, (text_hash, _text) in enumerate(ability_rows)]

    count = _store_model_embeddings_batches(model_id, iter_batches())
    logger.info("ONNX embedding complete. abilities=%d", count)
    return count


def _populate_model_embeddings(model_id: str, model_root: Path, bundle_root: Path, *, batch_size: int) -> tuple[int, str]:
    archive_path = _resolve_embeddings_archive_path(bundle_root)
    if archive_path is not None:
        precomputed = _store_precomputed_embeddings_from_archive(model_id, archive_path, batch_size=batch_size)
        if precomputed is not None:
            return precomputed, "precomputed"

    pytorch_model_path = _resolve_pytorch_model_path(bundle_root)
    if pytorch_model_path is not None:
        try:
            return (
                _compute_and_store_embeddings_from_pytorch_model(
                    model_id,
                    pytorch_model_path,
                    batch_size=batch_size,
                ),
                "pytorch",
            )
        except _MissingTorchError as exc:
            # Bundles ship both PyTorch and ONNX weights, but the API image is
            # built with `--extra api` and has no torch. Falling back to the
            # ONNX weights in the same bundle keeps promotion runnable there;
            # without this, promotion only ever works on a machine with the
            # training extras. Any other failure propagates.
            logger.info("PyTorch backend unavailable (%s); embedding via the bundle's ONNX weights.", exc)

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
        db.query(SemanticAbilityEmbedding).filter(SemanticAbilityEmbedding.model_id == model_id).delete()
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
