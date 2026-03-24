from __future__ import annotations

import json
import logging
from importlib import import_module
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from ..core.config import huggingface_cache_dir, semantic_model_path, semantic_onnx_model_path
from ..core.models import Card, CardFace, CardFaceSemanticEmbedding
from .text_prep import normalize_oracle_text

logger = logging.getLogger("ot_backend.embed.index")

_index: SemanticIndex | None = None


def _load_onnx_dependencies() -> tuple[Any, Any]:
    import os

    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    try:
        onnxruntime = import_module("onnxruntime")
        transformers = import_module("transformers")
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError(
            "onnxruntime and transformers are required for semantic inference. "
            "Install the API dependencies before using this module."
        ) from exc
    return getattr(onnxruntime, "InferenceSession"), getattr(transformers, "AutoTokenizer")


def _pooling_config_path(model_root: Path) -> Path:
    return model_root / "1_Pooling" / "config.json"


def _resolve_onnx_model_path(model_root: Path) -> Path:
    configured_root = semantic_model_path()
    if model_root == configured_root:
        return semantic_onnx_model_path()

    default_path = model_root / "onnx" / "model.onnx"
    legacy_path = model_root / "model.onnx"
    if default_path.exists():
        return default_path
    if legacy_path.exists():
        return legacy_path
    return default_path


def _validate_pooling_strategy(model_root: Path) -> None:
    pooling_config_path = _pooling_config_path(model_root)
    if not pooling_config_path.exists():
        return

    config = json.loads(pooling_config_path.read_text(encoding="utf-8"))
    if not config.get("pooling_mode_mean_tokens", True):
        raise RuntimeError("Semantic API supports only mean-token pooling for ONNX inference.")
    unsupported_modes = (
        config.get("pooling_mode_cls_token", False),
        config.get("pooling_mode_max_tokens", False),
        config.get("pooling_mode_lasttoken", False),
        config.get("pooling_mode_weightedmean_tokens", False),
    )
    if any(unsupported_modes):
        raise RuntimeError("Semantic API does not support the configured ONNX pooling strategy.")


def _mean_pool(token_embeddings: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    expanded_attention_mask = np.expand_dims(attention_mask, axis=-1).astype(np.float32)
    weighted_sum = np.sum(token_embeddings * expanded_attention_mask, axis=1)
    mask_sum = np.clip(np.sum(expanded_attention_mask, axis=1), a_min=1e-9, a_max=None)
    return weighted_sum / mask_sum


def _normalize_embeddings(embeddings: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    return embeddings / np.clip(norms, a_min=1e-12, a_max=None)


class OnnxTextEncoder:
    def __init__(self, model_root: Path | None = None):
        model_root = semantic_model_path() if model_root is None else model_root
        onnx_model_path = _resolve_onnx_model_path(model_root)
        if not onnx_model_path.exists():
            raise RuntimeError(f"Semantic ONNX artifact not found at {onnx_model_path}")

        _validate_pooling_strategy(model_root)
        InferenceSession, AutoTokenizer = _load_onnx_dependencies()
        huggingface_cache_dir()
        logger.info("Loading ONNX model from %s", onnx_model_path)
        self._tokenizer = AutoTokenizer.from_pretrained(str(model_root), local_files_only=True)
        self._session = InferenceSession(str(onnx_model_path), providers=["CPUExecutionProvider"])
        self._session_input_names = {session_input.name for session_input in self._session.get_inputs()}
        logger.info("Semantic model ready")

    def encode(self, text: str) -> list[float]:
        normalized = normalize_oracle_text(text)
        encoded = self._tokenizer(
            [normalized],
            padding=True,
            truncation=True,
            return_tensors="np",
        )
        session_inputs = {
            key: value
            for key, value in encoded.items()
            if key in self._session_input_names
        }
        outputs = self._session.run(None, session_inputs)
        token_embeddings = np.asarray(outputs[0], dtype=np.float32)
        attention_mask = np.asarray(encoded["attention_mask"], dtype=np.float32)
        pooled = _mean_pool(token_embeddings, attention_mask)
        normalized_embeddings = _normalize_embeddings(pooled)
        return normalized_embeddings[0].tolist()


class SemanticIndex:
    def __init__(self, model_root: Path | None = None):
        self.model = OnnxTextEncoder(model_root=model_root)

    def encode_query(self, text: str) -> list[float]:
        return self.model.encode(text)

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
