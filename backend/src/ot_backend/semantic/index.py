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
from sqlalchemy.orm import Session

from ..core.config import (
    configure_huggingface_env,
    semantic_active_model_poll_seconds,
    semantic_onnx_inter_op_threads,
    semantic_onnx_intra_op_threads,
)
from ..core.database import SessionLocal
from ..core.models import SemanticModel
from .embedding_matrix import EmbeddingMatrix
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
        tokenizers = import_module("tokenizers")
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError(
            "onnxruntime and tokenizers are required for semantic inference. "
            "Install the API dependencies before using this module."
        ) from exc
    return (
        getattr(onnxruntime, "InferenceSession"),
        getattr(onnxruntime, "SessionOptions"),
        getattr(tokenizers, "Tokenizer"),
    )


def _pooling_config_path(model_root: Path) -> Path:
    return model_root / "1_Pooling" / "config.json"


def _resolve_onnx_model_path(model_root: Path) -> Path:
    return model_root / "onnx" / "model.onnx"


def _read_max_seq_length(model_root: Path) -> int:
    sbert_config = model_root / "sentence_bert_config.json"
    if sbert_config.exists():
        try:
            cfg = type_cast(dict[str, Any], json.loads(sbert_config.read_text(encoding="utf-8")))
            value = cfg.get("max_seq_length")
            if isinstance(value, int) and value > 0:
                return value
        except (ValueError, OSError):
            pass
    return 512


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
        tokenizer_path = model_root / "tokenizer.json"
        if not tokenizer_path.exists():
            raise RuntimeError(
                f"Semantic bundle missing tokenizer.json at {tokenizer_path}; "
                "re-export the model with a recent sentence-transformers version."
            )

        _validate_pooling_strategy(model_root)
        InferenceSession, SessionOptions, Tokenizer = _load_onnx_dependencies()
        sess_options = SessionOptions()
        sess_options.log_severity_level = _ORT_LOG_SEVERITY_ERRORS_ONLY
        sess_options.intra_op_num_threads = semantic_onnx_intra_op_threads()
        sess_options.inter_op_num_threads = semantic_onnx_inter_op_threads()
        # Trade a tiny bit of latency for ~100-200 MB less resident memory:
        # ORT's CPU arena keeps freed allocations around for reuse, which
        # inflates RSS for an API that encodes one short query at a time.
        sess_options.enable_cpu_mem_arena = False
        sess_options.enable_mem_pattern = False
        configure_huggingface_env()
        logger.info("Loading ONNX model from %s", onnx_model_path)
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        max_length = _read_max_seq_length(model_root)
        self._tokenizer.enable_truncation(max_length=max_length)
        pad_id = self._tokenizer.token_to_id("[PAD]")
        if pad_id is None:
            pad_id = 0
        self._tokenizer.enable_padding(pad_id=pad_id, pad_token="[PAD]")
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
            encoded = self._tokenizer.encode_batch(batch)
            input_ids = np.asarray([enc.ids for enc in encoded], dtype=np.int64)
            attention_mask = np.asarray([enc.attention_mask for enc in encoded], dtype=np.int64)
            session_inputs: dict[str, np.ndarray] = {}
            if "input_ids" in self._session_input_names:
                session_inputs["input_ids"] = input_ids
            if "attention_mask" in self._session_input_names:
                session_inputs["attention_mask"] = attention_mask
            if "token_type_ids" in self._session_input_names:
                session_inputs["token_type_ids"] = np.asarray(
                    [enc.type_ids for enc in encoded], dtype=np.int64
                )
            outputs = self._session.run(None, session_inputs)
            token_embeddings = np.asarray(outputs[0], dtype=np.float32)
            pooled = _mean_pool(token_embeddings, attention_mask.astype(np.float32))
            normalized_embeddings = _normalize_embeddings(pooled)
            vectors.extend([[float(value) for value in row] for row in normalized_embeddings])
        return vectors


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


class SemanticIndex:
    model: OnnxTextEncoder
    _matrix: EmbeddingMatrix | None
    _matrix_lock: threading.Lock

    def __init__(self, model_root: Path, *, model_id: str | None = None):
        self.model = OnnxTextEncoder(model_root=model_root)
        self.model_id = model_id
        self._matrix = None
        self._matrix_lock = threading.Lock()

    def encode_query(self, text: str) -> list[float]:
        return self.model.encode(text)

    def warm(self) -> None:
        """Eagerly load the embedding matrix using a fresh DB session."""
        with SessionLocal() as db:
            self._ensure_matrix(db)

    def _ensure_matrix(self, db: Session) -> EmbeddingMatrix:
        if self._matrix is not None:
            return self._matrix
        with self._matrix_lock:
            if self._matrix is None:
                if self.model_id is None:
                    raise RuntimeError("SemanticIndex has no model_id; cannot load embedding matrix.")
                self._matrix = EmbeddingMatrix.load(db, self.model_id)
        return self._matrix

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
        matrix = self._ensure_matrix(db)
        seed_idx = matrix.key_to_idx.get(face_key)
        if seed_idx is None:
            return []
        return self._score(
            matrix,
            matrix.vectors[seed_idx],
            limit,
            exclude_idx=seed_idx,
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
        matrix = self._ensure_matrix(db)
        query_vec = np.asarray(self.encode_query(query), dtype=np.float32)
        norm = float(np.linalg.norm(query_vec))
        if norm > 0:
            query_vec = query_vec / norm
        return self._score(
            matrix,
            query_vec,
            limit,
            card_type=card_type,
            colors=colors,
            cmc_min=cmc_min,
            cmc_max=cmc_max,
            format=format,
            rarity=rarity,
            color_feature=color_feature,
            match_mode=match_mode,
        )

    @staticmethod
    def _score(
        matrix: EmbeddingMatrix,
        query_vec: FloatArray,
        limit: int,
        *,
        exclude_idx: int | None = None,
        card_type: list[str] | None = None,
        colors: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        format: list[str] | None = None,
        rarity: list[str] | None = None,
        color_feature: str = "identity",
        match_mode: str = "at_least",
    ) -> list[tuple[tuple[str, int], float]]:
        if matrix.vectors.size == 0 or limit <= 0:
            return []

        mask = matrix.filter_mask(
            card_type=card_type,
            colors=colors,
            cmc_min=cmc_min,
            cmc_max=cmc_max,
            format=format,
            rarity=rarity,
            color_feature=color_feature,
            match_mode=match_mode,
        )
        if exclude_idx is not None:
            mask[exclude_idx] = False

        kept = np.flatnonzero(mask)
        if kept.size == 0:
            return []

        scores = matrix.vectors[kept] @ query_vec  # (K,) cosine == dot for normalized vectors
        n = min(limit, kept.size)
        if n < kept.size:
            partition = np.argpartition(-scores, n - 1)[:n]
            ordered = partition[np.argsort(-scores[partition])]
        else:
            ordered = np.argsort(-scores)

        result_idx = kept[ordered]
        result_scores = scores[ordered]
        return [
            (matrix.face_keys[int(i)], round(float(result_scores[k]), 6))
            for k, i in enumerate(result_idx)
        ]


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
