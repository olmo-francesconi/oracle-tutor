from __future__ import annotations

import logging
from importlib import import_module

from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from ..core.config import huggingface_cache_dir, semantic_model_source
from .text_prep import normalize_oracle_text

logger = logging.getLogger("ot_backend.embed.index")

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
    def __init__(self, model_path: str | None = None):
        SentenceTransformer = _load_sentence_transformers()
        huggingface_cache_dir()
        resolved_model_source = semantic_model_source() if model_path is None else model_path
        self.model = SentenceTransformer(resolved_model_source)

    def encode_query(self, text: str) -> list[float]:
        normalized = normalize_oracle_text(text)
        return self.model.encode([normalized], normalize_embeddings=True)[0].tolist()

    def similar_to_face(
        self,
        face_id: int,
        limit: int,
        db: Session,
        card_type: str | None = None,
        colors: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        format: str | None = None,
        rarity: str | None = None,
        color_feature: str = "identity",
    ) -> list[tuple[int, float]]:
        CardFaceSemanticEmbedding = _load_semantic_model_class()
        seed = db.get(CardFaceSemanticEmbedding, face_id)
        if seed is None:
            return []
        return self._pgvector_query(
            seed.embedding,
            limit + 1,
            db,
            exclude=face_id,
            card_type=card_type,
            colors=colors,
            cmc_min=cmc_min,
            cmc_max=cmc_max,
            format=format,
            rarity=rarity,
            color_feature=color_feature,
        )

    def search_oracle(
        self,
        query: str,
        limit: int,
        db: Session,
        card_type: str | None = None,
        colors: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        format: str | None = None,
        rarity: str | None = None,
        color_feature: str = "identity",
    ) -> list[tuple[int, float]]:
        return self._pgvector_query(
            self.encode_query(query),
            limit,
            db,
            card_type=card_type,
            colors=colors,
            cmc_min=cmc_min,
            cmc_max=cmc_max,
            format=format,
            rarity=rarity,
            color_feature=color_feature,
        )

    def _pgvector_query(
        self,
        query_vec,
        limit: int,
        db: Session,
        exclude: int | None = None,
        card_type: str | None = None,
        colors: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        format: str | None = None,
        rarity: str | None = None,
        color_feature: str = "identity",
    ) -> list[tuple[int, float]]:
        CardFaceSemanticEmbedding = _load_semantic_model_class()
        from ..core.models import Card, CardFace

        distance = CardFaceSemanticEmbedding.embedding.cosine_distance(query_vec).label("distance")
        query = db.query(CardFaceSemanticEmbedding.face_id, distance)

        has_filters = any(value is not None for value in (card_type, colors, cmc_min, cmc_max, format, rarity))
        if has_filters:
            query = query.join(CardFace, CardFace.id == CardFaceSemanticEmbedding.face_id).join(Card, Card.id == CardFace.card_id)

        if exclude is not None:
            query = query.filter(CardFaceSemanticEmbedding.face_id != exclude)

        if card_type is not None:
            query = query.filter(CardFace.type_line.ilike(f"%{card_type}%"))

        if colors is not None:
            color_values: list[str] = []
            for ch in colors.upper():
                if ch in {"W", "U", "B", "R", "G"} and ch not in color_values:
                    color_values.append(ch)
            if color_values:
                if color_feature == "colors":
                    query = query.filter(cast(CardFace.colors, JSONB).contains(color_values))
                else:
                    query = query.filter(cast(Card.color_identity, JSONB).contains(color_values))

        if cmc_min is not None:
            query = query.filter(Card.cmc >= cmc_min)

        if cmc_max is not None:
            query = query.filter(Card.cmc <= cmc_max)

        if format is not None:
            query = query.filter(Card.legalities[format].astext.in_(["legal", "restricted"]))

        if rarity is not None:
            query = query.filter(Card.rarity == rarity)

        rows = query.order_by(distance).limit(limit).all()
        return [(row.face_id, round(1.0 - row.distance, 6)) for row in rows]


def get_semantic_index() -> SemanticIndex | None:
    global _index
    if _index is not None:
        return _index

    try:
        _index = SemanticIndex()
    except Exception as exc:
        logger.warning("Semantic index unavailable: %s", exc)
        return None
    return _index
