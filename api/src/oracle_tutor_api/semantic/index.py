from __future__ import annotations

import logging
import os
from importlib import import_module
from pathlib import Path

from sqlalchemy.orm import Session

from .text_prep import normalize_oracle_text

logger = logging.getLogger("oracle_tutor_api.semantic.index")

MODEL_PATH = os.environ.get("SEMANTIC_MODEL_PATH", "data/semantic/model")

_index: SemanticIndex | None = None


def _load_sentence_transformers():
    try:
        sentence_transformers = import_module("sentence_transformers")
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError(
            "sentence-transformers is required for semantic inference. "
            "Install the optional semantic extra before using this module."
        ) from exc
    return getattr(sentence_transformers, "SentenceTransformer")


def _load_semantic_model_class():
    try:
        from ..core.models import CardFaceSemanticEmbedding
    except Exception as exc:  # pragma: no cover - current branch safety
        raise RuntimeError("CardFaceSemanticEmbedding model is unavailable in the current codebase state.") from exc
    return CardFaceSemanticEmbedding


class SemanticIndex:
    def __init__(self, model_path: str = MODEL_PATH):
        SentenceTransformer = _load_sentence_transformers()
        self.model = SentenceTransformer(model_path)

    def encode_query(self, text: str) -> list[float]:
        normalized = normalize_oracle_text(text)
        return self.model.encode([normalized], normalize_embeddings=True)[0].tolist()

    def similar_to_face(self, face_id: int, limit: int, db: Session) -> list[tuple[int, float]]:
        CardFaceSemanticEmbedding = _load_semantic_model_class()
        seed = db.get(CardFaceSemanticEmbedding, face_id)
        if seed is None:
            return []
        return self._pgvector_query(seed.embedding, limit + 1, db, exclude=face_id)

    def search_oracle(self, query: str, limit: int, db: Session) -> list[tuple[int, float]]:
        return self._pgvector_query(self.encode_query(query), limit, db)

    def _pgvector_query(
        self,
        query_vec,
        limit: int,
        db: Session,
        exclude: int | None = None,
    ) -> list[tuple[int, float]]:
        CardFaceSemanticEmbedding = _load_semantic_model_class()
        distance = CardFaceSemanticEmbedding.embedding.cosine_distance(query_vec).label("distance")
        query = db.query(CardFaceSemanticEmbedding.face_id, distance)
        if exclude is not None:
            query = query.filter(CardFaceSemanticEmbedding.face_id != exclude)
        rows = query.order_by(distance).limit(limit).all()
        return [(row.face_id, round(1.0 - row.distance, 6)) for row in rows]


def get_semantic_index() -> SemanticIndex | None:
    global _index
    if _index is not None:
        return _index

    model_path = Path(MODEL_PATH)
    if not model_path.exists():
        return None

    try:
        _index = SemanticIndex(str(model_path))
    except Exception as exc:
        logger.warning("Semantic index unavailable at %s: %s", model_path, exc)
        return None
    return _index
