from __future__ import annotations

import logging
from importlib import import_module
from typing import Any

from ..core.config import huggingface_cache_dir, semantic_model_source
from ..core.database import SessionLocal
from ..core.models import CardFace
from .text_prep import face_to_text

logger = logging.getLogger("ot_backend.embed.compute")

BATCH_SIZE = 256


def _load_sentence_transformers() -> Any:
    try:
        sentence_transformers = import_module("sentence_transformers")
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError(
            "sentence-transformers is required for semantic embedding computation. "
            "Install the optional semantic extra before running this module."
        ) from exc
    return getattr(sentence_transformers, "SentenceTransformer")


def _load_embedding_model(model_path: str):
    SentenceTransformer = _load_sentence_transformers()
    huggingface_cache_dir()
    return SentenceTransformer(model_path)


def _load_semantic_models() -> Any:
    try:
        from ..core.models import CardFaceSemanticEmbedding
    except Exception as exc:  # pragma: no cover - current branch safety
        raise RuntimeError("CardFaceSemanticEmbedding model is unavailable in the current codebase state.") from exc
    return CardFaceSemanticEmbedding


def compute_and_store(db) -> None:
    CardFaceSemanticEmbedding = _load_semantic_models()
    model_source = semantic_model_source()
    cache_dir = huggingface_cache_dir()

    logger.info("Starting semantic embedding computation.")
    logger.info("  model_source=%s", model_source)
    logger.info("  cache_dir=%s", cache_dir)

    model = _load_embedding_model(model_source)
    logger.info("Semantic model loaded successfully for embedding computation.")
    faces = db.query(CardFace).all()
    logger.info("Loaded %d card faces for embedding computation.", len(faces))
    db.query(CardFaceSemanticEmbedding).delete()
    logger.info("Cleared existing semantic embeddings.")
    if not faces:
        db.commit()
        logger.warning("No faces found; cleared semantic embeddings and skipped recomputation.")
        return

    texts = [face_to_text(f) for f in faces]
    logger.info("Encoding %d face texts with batch_size=%d", len(texts), BATCH_SIZE)
    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    logger.info("Encoding complete. Persisting %d embeddings to the database.", len(faces))

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
