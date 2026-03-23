from __future__ import annotations

import logging
import os
from typing import Any

from ..core.database import SessionLocal
from ..core.models import CardFace
from .text_prep import face_to_text

logger = logging.getLogger("oracle_tutor_api.semantic.compute")

MODEL_PATH = os.environ.get("SEMANTIC_MODEL_PATH", "data/semantic/model")
BATCH_SIZE = 256


def _load_sentence_transformers() -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError(
            "sentence-transformers is required for semantic embedding computation. "
            "Install the optional semantic extra before running this module."
        ) from exc
    return SentenceTransformer


def _load_embedding_model(model_path: str):
    SentenceTransformer = _load_sentence_transformers()
    return SentenceTransformer(model_path)


def _load_semantic_models() -> Any:
    try:
        from ..core.models import CardFaceSemanticEmbedding
    except Exception as exc:  # pragma: no cover - current branch safety
        raise RuntimeError("CardFaceSemanticEmbedding model is unavailable in the current codebase state.") from exc
    return CardFaceSemanticEmbedding


def compute_and_store(db) -> None:
    CardFaceSemanticEmbedding = _load_semantic_models()

    model = _load_embedding_model(MODEL_PATH)
    faces = db.query(CardFace).all()
    db.query(CardFaceSemanticEmbedding).delete()
    if not faces:
        db.commit()
        logger.warning("No faces found; cleared semantic embeddings and skipped recomputation.")
        return

    texts = [face_to_text(f) for f in faces]
    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    for face, emb in zip(faces, embeddings):
        db.add(CardFaceSemanticEmbedding(face_id=face.id, embedding=emb.tolist()))
    db.commit()
    logger.info("Stored %d semantic embeddings.", len(faces))


def main() -> int:
    db = SessionLocal()
    try:
        compute_and_store(db)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
