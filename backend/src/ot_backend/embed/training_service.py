from __future__ import annotations

import logging
from importlib import import_module
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..core.config import huggingface_cache_dir
from ..core.database import SessionLocal
from ..core.models import CardFace
from .dataset_service import FaceIdentity, TrainingDatasetState
from .text_prep import face_to_text

logger = logging.getLogger("ot_backend.embed.training_service")

CHECKPOINT_DIR_NAME = "checkpoints"
EMBED_WRITE_BATCH_SIZE = 512


class LazyInputExampleDataset:
    def __init__(
        self,
        pair_ids: list[tuple[FaceIdentity, FaceIdentity]],
        face_texts: dict[FaceIdentity, str],
        input_example_cls: Any,
        direct_text_pairs: list[tuple[str, str]] | None = None,
    ) -> None:
        self._pair_ids = pair_ids
        self._face_texts = face_texts
        self._input_example_cls = input_example_cls
        self._direct_text_pairs = direct_text_pairs or []
        self._id_pair_count = len(pair_ids)

    def __len__(self) -> int:
        return self._id_pair_count + len(self._direct_text_pairs)

    def __getitem__(self, index: int) -> Any:
        if index < self._id_pair_count:
            left_face_key, right_face_key = self._pair_ids[index]
            return self._input_example_cls(texts=[self._face_texts[left_face_key], self._face_texts[right_face_key]])
        anchor, positive = self._direct_text_pairs[index - self._id_pair_count]
        return self._input_example_cls(texts=[anchor, positive])


def _load_sentence_transformers() -> tuple[Any, Any, Any]:
    try:
        st = import_module("sentence_transformers")
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "sentence-transformers is required for this pipeline. "
            "Install the semantic-worker extra before running."
        ) from exc
    return getattr(st, "SentenceTransformer"), getattr(st, "InputExample"), getattr(st, "losses")


def _load_sentence_transformer_class() -> Any:
    return _load_sentence_transformers()[0]


def _ensure_training_dependencies() -> None:
    required = {
        "datasets": "The `datasets` package is required.",
        "accelerate": "The `accelerate` package is required.",
    }
    for name, msg in required.items():
        try:
            import_module(name)
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"{msg} Install the semantic worker dependencies.") from exc


def _is_mps_available() -> bool:
    try:
        torch = import_module("torch")
    except Exception:
        return False
    mps = getattr(getattr(torch, "backends", None), "mps", None)
    return bool(mps is not None and getattr(mps, "is_available", lambda: False)())


def _fit_model(model: Any, **kwargs: Any) -> None:
    if _is_mps_available() and hasattr(model, "old_fit"):
        logger.info("Using legacy sentence-transformers training path on MPS.")
        model.old_fit(**kwargs)
        return
    model.fit(**kwargs)


def train_sentence_transformer(
    *,
    base_model: str,
    dataset_state: TrainingDatasetState,
    epochs: int,
    batch_size: int,
    warmup_divisor: int,
    min_warmup_steps: int,
    checkpoint_dir: Path,
) -> Any:
    SentenceTransformer, InputExample, losses = _load_sentence_transformers()
    _ensure_training_dependencies()
    cache_dir = huggingface_cache_dir()

    if not dataset_state.pair_ids:
        logger.error("No training examples found; cannot train.")
        raise RuntimeError("No training examples found.")

    logger.info("Loading base model: %s (cache_dir=%s)", base_model, cache_dir)
    model = SentenceTransformer(base_model)

    try:
        torch_utils_data = import_module("torch.utils.data")
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("torch is required for training.") from exc
    DataLoader = getattr(torch_utils_data, "DataLoader")

    training_dataset = LazyInputExampleDataset(
        dataset_state.pair_ids,
        dataset_state.face_texts,
        InputExample,
        direct_text_pairs=dataset_state.direct_text_pairs,
    )
    dataloader = DataLoader(training_dataset, shuffle=False, batch_size=batch_size)
    loss = losses.MultipleNegativesRankingLoss(model)

    warmup_steps = max(min_warmup_steps, len(training_dataset) // warmup_divisor)
    logger.info(
        "Training. examples=%d epochs=%d batch_size=%d warmup_steps=%d",
        len(training_dataset),
        epochs,
        batch_size,
        warmup_steps,
    )

    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    _fit_model(
        model,
        train_objectives=[(dataloader, loss)],
        epochs=epochs,
        warmup_steps=warmup_steps,
        show_progress_bar=True,
        checkpoint_path=str(checkpoint_dir),
    )
    logger.info("Training complete.")
    return model


def export_onnx_model(model_source: str, output_path: Path) -> None:
    SentenceTransformer = _load_sentence_transformer_class()
    cache_dir = huggingface_cache_dir()
    logger.info(
        "Exporting ONNX model. model_source=%s output_path=%s cache_dir=%s",
        model_source,
        output_path,
        cache_dir,
    )
    model = SentenceTransformer(
        model_source,
        backend="onnx",
        model_kwargs={
            "provider": "CPUExecutionProvider",
            "export": True,
            "file_name": "onnx/model.onnx",
        },
        local_files_only=Path(model_source).exists(),
    )
    output_path.mkdir(parents=True, exist_ok=True)
    model.save(str(output_path))
    logger.info("ONNX model saved to %s", output_path)


def _iter_faces(db: Session, *, batch_size: int):
    last_oracle_id: str | None = None
    last_face_ix: int | None = None
    while True:
        query = select(CardFace).order_by(CardFace.oracle_id, CardFace.face_ix).limit(batch_size)
        if last_oracle_id is not None and last_face_ix is not None:
            query = query.where(
                or_(
                    CardFace.oracle_id > last_oracle_id,
                    and_(CardFace.oracle_id == last_oracle_id, CardFace.face_ix > last_face_ix),
                )
            )
        faces = list(db.scalars(query))
        if not faces:
            return
        for face in faces:
            yield face
        last_oracle_id = faces[-1].oracle_id
        last_face_ix = faces[-1].face_ix


def _write_embeddings_snapshot(
    oracle_ids: list[str],
    face_ixs: list[int],
    embeddings: list[np.ndarray],
    *,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_path,
        oracle_ids=np.asarray(oracle_ids),
        face_ixs=np.asarray(face_ixs, dtype=np.int32),
        embeddings=np.asarray(embeddings, dtype=np.float32),
    )
    logger.info("Saved embedding snapshot to %s", output_path)


def compute_embeddings(model: Any, batch_size: int = 256, output_path: Path | None = None) -> int:
    try:
        from ..core.models import CardFaceSemanticEmbedding
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("CardFaceSemanticEmbedding model is unavailable.") from exc

    db = SessionLocal()
    try:
        db.query(CardFaceSemanticEmbedding).delete()
        total = db.query(CardFace).count()
        logger.info("Computing embeddings for %d card faces (batch_size=%d).", total, batch_size)
        if total == 0:
            db.commit()
            logger.warning("No faces found; skipped embedding computation.")
            return 0

        snapshot_oracle_ids: list[str] = []
        snapshot_face_ixs: list[int] = []
        snapshot_embeddings: list[np.ndarray] = []
        buffered_faces: list[CardFace] = []
        buffered_texts: list[str] = []
        stored = 0

        def flush_batch() -> None:
            nonlocal stored
            if not buffered_faces:
                return
            encoded = np.asarray(
                model.encode(
                    buffered_texts,
                    batch_size=batch_size,
                    normalize_embeddings=True,
                    show_progress_bar=stored == 0,
                ),
                dtype=np.float32,
            )
            db.bulk_insert_mappings(
                CardFaceSemanticEmbedding,
                [
                    {
                        "oracle_id": face.oracle_id,
                        "face_ix": face.face_ix,
                        "embedding": emb.tolist(),
                    }
                    for face, emb in zip(buffered_faces, encoded, strict=False)
                ],
            )
            if output_path is not None:
                snapshot_oracle_ids.extend(face.oracle_id for face in buffered_faces)
                snapshot_face_ixs.extend(face.face_ix for face in buffered_faces)
                snapshot_embeddings.extend(encoded)
            stored += len(buffered_faces)
            buffered_faces.clear()
            buffered_texts.clear()

        for face in _iter_faces(db, batch_size=EMBED_WRITE_BATCH_SIZE):
            buffered_faces.append(face)
            buffered_texts.append(face_to_text(face))
            if len(buffered_faces) >= EMBED_WRITE_BATCH_SIZE:
                flush_batch()

        flush_batch()
        if output_path is not None:
            _write_embeddings_snapshot(
                snapshot_oracle_ids,
                snapshot_face_ixs,
                snapshot_embeddings,
                output_path=output_path,
            )
        db.commit()
        logger.info("Stored %d embeddings.", stored)
        return stored
    finally:
        db.close()
