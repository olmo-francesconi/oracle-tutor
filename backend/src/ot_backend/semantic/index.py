from __future__ import annotations

import json
import logging
import threading
import time
import warnings
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path
from typing import Any
from typing import cast as type_cast

import numpy as np
import numpy.typing as npt
from sqlalchemy import and_, cast, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from ..core.config import (
    configure_huggingface_env,
    semantic_active_model_poll_seconds,
    semantic_onnx_inter_op_threads,
    semantic_onnx_intra_op_threads,
)
from ..core.database import SessionLocal
from ..core.models import Card, CardFace, SemanticModel, SemanticModelEmbedding
from .model_registry import get_active_semantic_model_id, materialize_semantic_model
from .text_prep import normalize_oracle_text

logger = logging.getLogger("ot_backend.semantic.index")

_index: SemanticIndex | None = None
_UNSET = object()  # Sentinel: index has never been loaded (distinct from None = no active model)
_loaded_model_id: str | None | object = _UNSET
_last_refresh_check: float = 0.0
_index_lock = threading.Lock()
_ORT_LOG_SEVERITY_ERRORS_ONLY = 3
FloatArray = npt.NDArray[np.float32]


# ---------------------------------------------------------------------------
# ONNX loading
# ---------------------------------------------------------------------------


def _load_onnx_dependencies() -> tuple[Any, Any, Any]:
    import os

    _ = os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    warnings.filterwarnings("ignore", category=FutureWarning, module="transformers")
    try:
        onnxruntime = import_module("onnxruntime")
        transformers = import_module("transformers")
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError(
            "onnxruntime and transformers are required for semantic inference. "
            "Install the API dependencies before using this module."
        ) from exc
    return (
        getattr(onnxruntime, "InferenceSession"),
        getattr(onnxruntime, "SessionOptions"),
        getattr(transformers, "AutoTokenizer"),
    )


def _pooling_config_path(model_root: Path) -> Path:
    return model_root / "1_Pooling" / "config.json"


def _resolve_onnx_model_path(model_root: Path) -> Path:
    return model_root / "onnx" / "model.onnx"


def _validate_pooling_strategy(model_root: Path) -> None:
    pooling_config_path = _pooling_config_path(model_root)
    if not pooling_config_path.exists():
        return

    config = type_cast(dict[str, bool], json.loads(pooling_config_path.read_text(encoding="utf-8")))
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


# ---------------------------------------------------------------------------
# Math / pooling
# ---------------------------------------------------------------------------


def _mean_pool(token_embeddings: FloatArray, attention_mask: FloatArray) -> FloatArray:
    expanded_attention_mask = np.expand_dims(attention_mask, axis=-1).astype(np.float32)
    weighted_sum = np.sum(token_embeddings * expanded_attention_mask, axis=1)
    mask_sum = np.clip(np.sum(expanded_attention_mask, axis=1), a_min=1e-9, a_max=None)
    return np.asarray(weighted_sum / mask_sum, dtype=np.float32)


def _normalize_embeddings(embeddings: FloatArray) -> FloatArray:
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    return np.asarray(embeddings / np.clip(norms, a_min=1e-12, a_max=None), dtype=np.float32)


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------


class OnnxTextEncoder:
    _tokenizer: Any
    _session: Any
    _session_input_names: set[str]

    def __init__(self, model_root: Path):
        onnx_model_path = _resolve_onnx_model_path(model_root)
        if not onnx_model_path.exists():
            raise RuntimeError(f"Semantic ONNX artifact not found at {onnx_model_path}")

        _validate_pooling_strategy(model_root)
        InferenceSession, SessionOptions, AutoTokenizer = _load_onnx_dependencies()
        sess_options = SessionOptions()
        sess_options.log_severity_level = _ORT_LOG_SEVERITY_ERRORS_ONLY
        sess_options.intra_op_num_threads = semantic_onnx_intra_op_threads()
        sess_options.inter_op_num_threads = semantic_onnx_inter_op_threads()
        configure_huggingface_env()
        logger.info("Loading ONNX model from %s", onnx_model_path)
        self._tokenizer = AutoTokenizer.from_pretrained(str(model_root), local_files_only=True)
        self._session = InferenceSession(
            str(onnx_model_path),
            sess_options=sess_options,
            providers=["CPUExecutionProvider"],
        )
        self._session_input_names = {session_input.name for session_input in self._session.get_inputs()}
        logger.info("Semantic model ready")

    def encode(self, text: str) -> list[float]:
        return self.encode_many([text], batch_size=1, normalize_inputs=True)[0]

    def encode_many(
        self,
        texts: Sequence[str],
        batch_size: int = 32,
        *,
        normalize_inputs: bool = True,
    ) -> list[list[float]]:
        if not texts:
            return []

        total = len(texts)
        effective_batch = max(1, batch_size)
        vectors: list[list[float]] = []
        for start in range(0, total, effective_batch):
            logger.debug("Encoding batch %d-%d / %d", start + 1, min(start + effective_batch, total), total)
            raw_batch = texts[start : start + effective_batch]
            batch = [normalize_oracle_text(text) for text in raw_batch] if normalize_inputs else list(raw_batch)
            encoded = self._tokenizer(
                batch,
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
            vectors.extend([[float(value) for value in row] for row in normalized_embeddings])
        return vectors


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


class SemanticIndex:
    model: OnnxTextEncoder

    def __init__(self, model_root: Path, *, model_id: str | None = None):
        self.model = OnnxTextEncoder(model_root=model_root)
        self.model_id = model_id

    def encode_query(self, text: str) -> list[float]:
        return self.model.encode(text)

    def similar_to_face(
        self,
        face_key: tuple[str, int],
        limit: int,
        db: Session,
        card_type: list[str] | None = None,
        colors: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        format: list[str] | None = None,
        rarity: list[str] | None = None,
        color_feature: str = "identity",
        match_mode: str = "at_least",
    ) -> list[tuple[tuple[str, int], float]]:
        seed = db.get(SemanticModelEmbedding, (self.model_id, *face_key))
        if seed is None:
            return []
        return self._pgvector_query(
            seed.embedding,
            limit + 1,
            db,
            exclude=face_key,
            card_type=card_type,
            colors=colors,
            cmc_min=cmc_min,
            cmc_max=cmc_max,
            format=format,
            rarity=rarity,
            color_feature=color_feature,
            match_mode=match_mode,
        )

    def search_oracle(
        self,
        query: str,
        limit: int,
        db: Session,
        card_type: list[str] | None = None,
        colors: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        format: list[str] | None = None,
        rarity: list[str] | None = None,
        color_feature: str = "identity",
        match_mode: str = "at_least",
    ) -> list[tuple[tuple[str, int], float]]:
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
            match_mode=match_mode,
        )

    def _pgvector_query(
        self,
        query_vec: Sequence[float],
        limit: int,
        db: Session,
        exclude: tuple[str, int] | None = None,
        card_type: list[str] | None = None,
        colors: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        format: list[str] | None = None,
        rarity: list[str] | None = None,
        color_feature: str = "identity",
        match_mode: str = "at_least",
    ) -> list[tuple[tuple[str, int], float]]:
        distance = SemanticModelEmbedding.embedding.cosine_distance(query_vec).label("distance")
        query = (
            db.query(SemanticModelEmbedding.oracle_id, SemanticModelEmbedding.face_ix, distance)
            .filter(SemanticModelEmbedding.model_id == self.model_id)
        )

        has_filters = any(value is not None for value in (card_type, colors, cmc_min, cmc_max, format)) or bool(rarity)
        if has_filters:
            query = query.join(
                CardFace,
                and_(
                    CardFace.oracle_id == SemanticModelEmbedding.oracle_id,
                    CardFace.face_ix == SemanticModelEmbedding.face_ix,
                ),
            ).join(Card, Card.oracle_id == CardFace.oracle_id)

        if exclude is not None:
            oracle_id_ex, face_ix_ex = exclude
            query = query.filter(
                ~and_(
                    SemanticModelEmbedding.oracle_id == oracle_id_ex,
                    SemanticModelEmbedding.face_ix == face_ix_ex,
                )
            )

        if card_type:
            # Array overlap against the GIN-indexed type_categories column.
            query = query.filter(CardFace.type_categories.op("&&")(card_type))

        if colors is not None:
            color_values: list[str] = []
            for ch in colors.upper():
                if ch in {"W", "U", "B", "R", "G"} and ch not in color_values:
                    color_values.append(ch)
            if color_values:
                color_source = cast(CardFace.colors, JSONB) if color_feature == "colors" else cast(Card.color_identity, JSONB)

                if match_mode == "exact":
                    query = query.filter(color_source.contains(color_values))
                    query = query.filter(color_source.contained_by(color_values))
                elif match_mode == "at_most":
                    query = query.filter(color_source.contained_by(color_values))
                else:
                    query = query.filter(color_source.contains(color_values))

        if cmc_min is not None:
            query = query.filter(Card.cmc >= cmc_min)

        if cmc_max is not None:
            query = query.filter(Card.cmc <= cmc_max)

        if format:
            query = query.filter(
                or_(*(Card.legalities.op("->>")(value).in_(["legal", "restricted"]) for value in format))
            )

        if rarity:
            query = query.filter(Card.rarity.in_(rarity))

        rows = query.order_by(distance).limit(limit).all()
        return [((row.oracle_id, row.face_ix), round(1.0 - row.distance, 6)) for row in rows]


# ---------------------------------------------------------------------------
# Module accessor
# ---------------------------------------------------------------------------


def get_semantic_index() -> SemanticIndex | None:
    global _index, _last_refresh_check, _loaded_model_id

    # Fast path: if index is loaded and poll interval hasn't elapsed, skip refresh check
    now = time.monotonic()
    poll_seconds = max(0.0, semantic_active_model_poll_seconds())
    if _index is not None and now - _last_refresh_check < poll_seconds:
        return _index

    # Check DB for active model ID — no lock held during network I/O
    try:
        with SessionLocal() as db:
            active_model_id = get_active_semantic_model_id(db)
    except Exception as exc:
        logger.warning("Semantic index DB check failed: %s", exc)
        return _index

    # Under lock: record that we checked, and skip reload if model ID is unchanged
    with _index_lock:
        _last_refresh_check = time.monotonic()
        if active_model_id is None:
            if _index is not None:
                logger.info("Clearing semantic index cache because no active model is configured.")
            _index = None
            _loaded_model_id = None
            return None
        if _index is not None and _loaded_model_id is not _UNSET and _loaded_model_id == active_model_id:
            return _index

    # S3 download + ONNX load happen OUTSIDE the lock
    try:
        with SessionLocal() as db:
            active_model = db.get(SemanticModel, active_model_id)
        if active_model is None:
            return _index
        model_root, _bundle_root = materialize_semantic_model(active_model)
        new_index = SemanticIndex(model_root=model_root, model_id=active_model.id)
    except Exception as exc:
        logger.warning("Semantic index unavailable: %s", exc)
        with _index_lock:
            _index = None
            _loaded_model_id = active_model_id
        return None

    # Swap the index under lock — fast operation
    with _index_lock:
        _index = new_index
        _loaded_model_id = active_model_id
    return _index


def mark_semantic_index_stale() -> None:
    global _last_refresh_check
    _last_refresh_check = 0.0
