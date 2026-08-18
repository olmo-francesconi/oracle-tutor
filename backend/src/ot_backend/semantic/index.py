from __future__ import annotations

import json
import logging
import threading
import time
import warnings
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any
from typing import cast as type_cast

import numpy as np
import numpy.typing as npt
from sqlalchemy import and_, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from ..core.config import (
    configure_huggingface_env,
    semantic_active_model_poll_seconds,
    semantic_onnx_inter_op_threads,
    semantic_onnx_intra_op_threads,
)
from ..core.database import SessionLocal
from ..core.models import Card, CardFace, CardFaceAbility, SemanticAbilityEmbedding, SemanticModel
from .ability_split import split_query_abilities
from .model_registry import get_active_semantic_model_id, materialize_semantic_model
from .semantic_state import get_semantic_data_version
from .text_prep import normalize_oracle_text

logger = logging.getLogger("ot_backend.semantic.index")

_index: SemanticIndex | None = None
_UNSET = object()  # Sentinel: index has never been loaded (distinct from None = no active model)
_loaded_model_id: str | None | object = _UNSET
# The ability store caches the whole corpus in this process, so a re-ingest
# that adds cards must invalidate it. Ingest bumps semantic_data_version, and
# it is the only signal that crosses process boundaries — the worker's own
# call to mark_semantic_index_stale() cannot reach the API's memory.
_loaded_data_version: int | None = None
_last_refresh_check: float = 0.0
_index_lock = threading.Lock()
_ORT_LOG_SEVERITY_ERRORS_ONLY = 3
IntArray = np.ndarray[Any, np.dtype[np.int64]]
FloatArray = npt.NDArray[np.float32]

_VALID_COLORS = frozenset({"W", "U", "B", "R", "G"})

# Retrieval is exact and complete: every face that passes the filter is scored,
# however low its similarity. There is no candidate cut, because there is no
# approximate index to justify one — the whole ability matrix is 37k x 384
# floats (57 MB) and a query is one matmul against it.
#
# The previous two-stage design took the 256 nearest ability texts BEFORE
# applying filters, so a filter anticorrelated with the query threw away almost
# everything: "counter target spell" restricted to mono-green reached the
# scorer with 55 of 4,952 eligible faces. It also capped any single-ability
# query at 400 results no matter the requested limit.
# How far below the best-matching ability another ability may sit and still be
# considered "matched just as well" when picking which one to show the user.
_DISPLAY_SIMILARITY_MARGIN = 0.05
# Distinct filter combinations whose face masks are kept.
_MASK_CACHE_ENTRIES = 64
# Rejected-ability band. Cosine similarity between short ability texts has a
# high floor — "Flying" scores ~0.67 against "Vigilance" and ~0.74 against
# "Shadow" — so a raw `1 - sim` penalty would shave every card by two thirds and
# make the reported match percentage meaningless. Only the band above the floor
# carries signal: measured against "Flying", exact restatements sit at 0.99+,
# compound lines that contain it ("Flying; fear") at ~0.84, and everything
# unrelated below 0.78. So similarity is ramped linearly across the band and
# anything at the top is dropped outright — "not this ability" has to actually
# remove the cards that print it, not just rank them lower.
_REJECT_IGNORE_SIMILARITY = 0.70
_REJECT_EXCLUDE_SIMILARITY = 0.90


@dataclass(frozen=True)
class SimilarityHit:
    """A scored card face plus the ability that drove the match."""

    face_key: tuple[str, int]
    score: float
    matched_ability: str | None = None


# ---------------------------------------------------------------------------
# ONNX loading
# ---------------------------------------------------------------------------


def _load_onnx_dependencies() -> tuple[Any, Any, Any, Any]:
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
        getattr(onnxruntime, "GraphOptimizationLevel"),
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


def _segment_max(values: FloatArray, starts: IntArray) -> FloatArray:
    """Max within each face's slice of the flat ability array."""
    return np.maximum.reduceat(values, starts, axis=0)


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
        InferenceSession, SessionOptions, GraphOptimizationLevel, Tokenizer = _load_onnx_dependencies()
        sess_options = SessionOptions()
        sess_options.log_severity_level = _ORT_LOG_SEVERITY_ERRORS_ONLY
        sess_options.intra_op_num_threads = semantic_onnx_intra_op_threads()
        sess_options.inter_op_num_threads = semantic_onnx_inter_op_threads()
        # Trade a tiny bit of latency for ~100-200 MB less resident memory:
        # ORT's CPU arena keeps freed allocations around for reuse, which
        # inflates RSS for an API that encodes one short query at a time.
        sess_options.enable_cpu_mem_arena = False
        sess_options.enable_mem_pattern = False
        # ENABLE_ALL (the default) does aggressive op fusion that keeps both the
        # original AND the fused weights resident — costs ~80 MB on a MiniLM
        # bundle. BASIC does constant folding only, no duplicate buffer; first
        # inference is ~10% slower, warm path is identical.
        sess_options.graph_optimization_level = GraphOptimizationLevel.ORT_ENABLE_BASIC
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
# Filter helpers
# ---------------------------------------------------------------------------


def _parse_color_chars(colors: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for ch in colors:
        up = ch.upper()
        if up in _VALID_COLORS and up not in seen:
            seen.add(up)
            ordered.append(up)
    return ordered


def _apply_filters(
    stmt: Select[Any],
    *,
    card_type: list[str] | None,
    colors: str | None,
    cmc_min: float | None,
    cmc_max: float | None,
    format: list[str] | None,
    rarity: list[str] | None,
    color_feature: str,
    match_mode: str,
):
    if card_type:
        stmt = stmt.where(CardFace.type_categories.overlap(card_type))

    if colors:
        wanted = _parse_color_chars(colors)
        if wanted:
            target = Card.color_identity if color_feature == "identity" else CardFace.colors
            wanted_jsonb = cast(wanted, JSONB)
            if match_mode == "exact":
                stmt = stmt.where(
                    target.op("@>")(wanted_jsonb),
                    target.op("<@")(wanted_jsonb),
                )
            elif match_mode == "at_most":
                stmt = stmt.where(target.op("<@")(wanted_jsonb))
            else:  # at_least
                stmt = stmt.where(target.op("@>")(wanted_jsonb))

    if cmc_min is not None:
        stmt = stmt.where(Card.cmc.is_not(None), Card.cmc >= cmc_min)
    if cmc_max is not None:
        stmt = stmt.where(Card.cmc.is_not(None), Card.cmc <= cmc_max)

    if format:
        clauses = [
            Card.legalities.op("->>")(fmt).in_(["legal", "restricted"])
            for fmt in format
        ]
        stmt = stmt.where(or_(*clauses))

    if rarity:
        stmt = stmt.where(Card.rarity.in_(rarity))

    return stmt


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _AbilityStore:
    """The whole ability corpus, laid out for one matmul per query.

    Vectors are keyed by DISTINCT ability text (~37k), not by instance (~63k),
    because that is how they are stored and embedded — "Flying" is one row, not
    3,235. Instances are held in a flat CSR-style layout ordered by face, so a
    per-face aggregate is a single `reduceat` rather than a Python loop.
    """

    vectors: FloatArray            # (n_texts, dim) unit-normalized
    inst_row: IntArray             # (n_inst,) -> row in `vectors`
    inst_text: list[str]           # (n_inst,) printed text, for `matched_ability`
    inst_idf: FloatArray           # (n_inst,) document-frequency weight
    starts: IntArray               # (n_faces,) segment start per face
    ends: IntArray                 # (n_faces,) segment end per face
    face_keys: list[tuple[str, int]]
    face_pos: dict[tuple[str, int], int]
    idf_of_hash: dict[str, float]

    @property
    def n_faces(self) -> int:
        return len(self.face_keys)


def _build_ability_store(db: Session, model_id: str) -> _AbilityStore:
    """Load every embedded ability once, at index construction."""
    total_texts = int(
        db.execute(
            select(func.count())
            .select_from(SemanticAbilityEmbedding)
            .where(SemanticAbilityEmbedding.model_id == model_id)
        ).scalar()
        or 0
    )
    if total_texts == 0:
        return _AbilityStore(
            np.zeros((0, 0), dtype=np.float32), np.zeros(0, dtype=np.int64), [],
            np.zeros(0, dtype=np.float32), np.zeros(0, dtype=np.int64),
            np.zeros(0, dtype=np.int64), [], {}, {},
        )

    # Streamed into a preallocated array rather than materialised as a list of
    # rows: each vector arrives as 384 Python floats, so holding all 37k at once
    # costs ~400 MB of transient objects for a 57 MB result.
    vectors: FloatArray = np.zeros((0, 0), dtype=np.float32)
    row_of_hash: dict[str, int] = {}
    cursor = db.execute(
        select(SemanticAbilityEmbedding.text_hash, SemanticAbilityEmbedding.embedding)
        .where(SemanticAbilityEmbedding.model_id == model_id)
        .execution_options(stream_results=True, yield_per=2048)
    )
    filled = 0
    for chunk in cursor.partitions():
        block = np.asarray([vec for _hash, vec in chunk], dtype=np.float32)
        if vectors.size == 0:
            vectors = np.empty((total_texts, block.shape[1]), dtype=np.float32)
        vectors[filled : filled + len(block)] = block
        for offset, (text_hash, _vec) in enumerate(chunk):
            row_of_hash[str(text_hash)] = filled + offset
        filled += len(block)
        del block, chunk
    vectors = vectors[:filled]
    # Defensive: promotion normalizes, but a dot product is only cosine if they are.
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)

    abilities = db.execute(
        select(
            CardFaceAbility.oracle_id,
            CardFaceAbility.face_ix,
            CardFaceAbility.text,
            CardFaceAbility.text_hash,
        ).order_by(
            CardFaceAbility.oracle_id, CardFaceAbility.face_ix, CardFaceAbility.ability_ix
        )
    ).all()

    counts: Counter[str] = Counter(str(r.text_hash) for r in abilities)
    total = float(sum(counts.values())) or 1.0
    # log1p(N/df): "Flying" (df~3235) lands near 2.5 while a one-off ability lands
    # near 11, so distinctive text dominates without common text being zeroed out.
    idf_of_hash = {h: float(np.log1p(total / max(1, c))) for h, c in counts.items()}
    default_idf = float(np.log1p(1.0))

    inst_row: list[int] = []
    inst_text: list[str] = []
    inst_idf: list[float] = []
    starts: list[int] = []
    ends: list[int] = []
    face_keys: list[tuple[str, int]] = []
    current: tuple[str, int] | None = None
    for record in abilities:
        # An ability whose text was never embedded cannot be scored. Skipping it
        # here (rather than scoring it as zero) keeps a partially embedded corpus
        # honest; a face left with nothing is dropped below.
        row = row_of_hash.get(str(record.text_hash))
        if row is None:
            continue
        key = (record.oracle_id, record.face_ix)
        if key != current:
            if current is not None:
                ends.append(len(inst_row))
            current = key
            face_keys.append(key)
            starts.append(len(inst_row))
        inst_row.append(row)
        inst_text.append(record.text or "")
        inst_idf.append(idf_of_hash.get(str(record.text_hash), default_idf))
    if current is not None:
        ends.append(len(inst_row))

    logger.info(
        "Ability store ready. texts=%d instances=%d faces=%d matrix=%.0f MB",
        filled, len(inst_row), len(face_keys), vectors.nbytes / 1e6,
    )
    return _AbilityStore(
        vectors=vectors,
        inst_row=np.asarray(inst_row, dtype=np.int64),
        inst_text=inst_text,
        inst_idf=np.asarray(inst_idf, dtype=np.float32),
        starts=np.asarray(starts, dtype=np.int64),
        ends=np.asarray(ends, dtype=np.int64),
        face_keys=face_keys,
        face_pos={key: i for i, key in enumerate(face_keys)},
        idf_of_hash=idf_of_hash,
    )


class SemanticIndex:
    model: OnnxTextEncoder
    model_id: str | None
    # Class-level default, not just an __init__ assignment: callers construct
    # this via object.__new__ to get a DB-only index without loading ONNX.
    _idf: dict[str, float] | None = None
    _store: "_AbilityStore | None" = None
    _mask_cache_store: "dict[tuple[Any, ...], FloatArray] | None" = None

    @property
    def _mask_cache(self) -> dict[tuple[Any, ...], FloatArray]:
        cache = self._mask_cache_store
        if cache is None:
            cache = {}
            self._mask_cache_store = cache
        return cache

    def __init__(self, model_root: Path, *, model_id: str | None = None):
        self.model = OnnxTextEncoder(model_root=model_root)
        self.model_id = model_id
        self._idf = None

    def _idf_weights(self, db: Session, text_hashes: Sequence[str]) -> FloatArray:
        """Inverse document frequency per distinct ability text.

        Loaded once per index instance (~37k rows) and reused. Document
        frequencies only change on re-ingest, and a slightly stale weight just
        nudges ranking, so this is not refreshed per request.
        """
        if self._idf is None:
            rows = db.execute(
                select(CardFaceAbility.text_hash, func.count())
                .group_by(CardFaceAbility.text_hash)
            ).all()
            total = float(sum(int(count) for _hash, count in rows)) or 1.0
            # log1p(N/df): "Flying" (df~3235) lands near 2.5 while a one-off
            # ability lands near 11, so distinctive text dominates without
            # common text being zeroed out entirely.
            self._idf = {
                str(text_hash): float(np.log1p(total / max(1, int(count))))
                for text_hash, count in rows
            }
        default = float(np.log1p(1.0))
        return np.asarray([self._idf.get(h, default) for h in text_hashes], dtype=np.float32)

    def encode_query(self, text: str) -> list[float]:
        return self.model.encode(text)

    def encode_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return self.model.encode_many(list(texts), batch_size=max(1, len(texts)))

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
        include_abilities: Sequence[int] | None = None,
        exclude_abilities: Sequence[int] | None = None,
    ) -> list[SimilarityHit]:
        """Find faces whose *ability set* resembles this face's ability set.

        Scored with a bidirectional Chamfer mean (see `_chamfer_rerank`): a card
        ranks highly when most of what it does is matched by the seed AND most
        of what the seed does is matched by it. Sharing one keyword is not
        enough on its own.

        `include_abilities` narrows the seed to a subset of the face's abilities
        and `exclude_abilities` names abilities the user does *not* want; a
        rejected ability is dropped from the seed as well as penalized on the
        candidate side, since searching by the very text you asked to avoid
        makes no sense. Rejecting everything the face does leaves nothing to
        match on and returns no results.

        Scoring only switches to forward/max-pool when the selection genuinely
        narrows the ability set, for the same reason text search does: having
        asked for cards that *have* these abilities, the user should not see
        them demoted for also doing things they never ruled out. Selecting every
        ability narrows nothing, so it scores exactly like the untuned search.
        """
        if self.model_id is None:
            return []
        default = self._load_face_abilities(db, face_key)
        if default is None:
            # No embedded abilities for this face (unknown oracle_id, or a model
            # whose embeddings predate it): nothing to match on.
            return []
        default_ixs = default[2]

        if include_abilities:
            seed = self._load_face_abilities(db, face_key, ability_ixs=include_abilities)
        elif exclude_abilities:
            rejected_ixs = set(exclude_abilities)
            kept = [ix for ix in default_ixs if ix not in rejected_ixs]
            seed = self._load_face_abilities(db, face_key, ability_ixs=kept) if kept else None
        else:
            seed = default
        if seed is None:
            return []
        seed_vectors, seed_hashes, seed_ixs = seed

        reject_vectors: FloatArray | None = None
        if exclude_abilities:
            rejected = self._load_face_abilities(db, face_key, ability_ixs=exclude_abilities)
            if rejected is not None:
                reject_vectors = rejected[0]

        return self._score(
            db,
            seed_vectors,
            limit,
            bidirectional=set(seed_ixs) == set(default_ixs),
            seed_hashes=seed_hashes,
            reject_vectors=reject_vectors,
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
    ) -> list[SimilarityHit]:
        """Find faces that *have* an ability matching the query text.

        The query is segmented the same way card text is (see
        `split_query_abilities`), so "flying // draw a card when this attacks"
        searches for two abilities rather than one muddled average of both.
        Each becomes its own probe, and `forward` then averages, over the
        abilities the user typed, how well the card's best ability matches each
        — i.e. AND semantics across the query.

        Deliberately max-pooled rather than bidirectional: someone searching
        "draw a card when a creature dies" wants cards with that ability, and
        should not see them demoted for also having flying and four other
        abilities the query never mentioned.

        The seed side is deliberately NOT IDF-weighted (`seed_hashes=None`),
        unlike card-to-card search: the user typed each ability on purpose, so
        a common one like "flying" must count as much as a rare one.
        """
        if self.model_id is None:
            return []
        query_abilities = split_query_abilities(query)
        if not query_abilities:
            return []
        query_vecs = np.asarray(self.encode_queries(query_abilities), dtype=np.float32)
        return self._score(
            db,
            query_vecs,
            limit,
            bidirectional=False,
            card_type=card_type,
            colors=colors,
            cmc_min=cmc_min,
            cmc_max=cmc_max,
            format=format,
            rarity=rarity,
            color_feature=color_feature,
            match_mode=match_mode,
        )

    def _load_face_abilities(
        self,
        db: Session,
        face_key: tuple[str, int],
        *,
        ability_ixs: Sequence[int] | None = None,
    ) -> tuple[FloatArray, list[str], list[int]] | None:
        """Return (vectors, text hashes, ability indices) for one face."""
        stmt = (
            select(
                CardFaceAbility.ability_ix,
                CardFaceAbility.text_hash,
                SemanticAbilityEmbedding.embedding,
            )
            .join(
                SemanticAbilityEmbedding,
                and_(
                    SemanticAbilityEmbedding.text_hash == CardFaceAbility.text_hash,
                    SemanticAbilityEmbedding.model_id == self.model_id,
                ),
            )
            .where(
                CardFaceAbility.oracle_id == face_key[0],
                CardFaceAbility.face_ix == face_key[1],
            )
        )
        if ability_ixs is not None:
            stmt = stmt.where(CardFaceAbility.ability_ix.in_(list(ability_ixs)))
        rows = db.execute(stmt.order_by(CardFaceAbility.ability_ix)).all()
        if not rows:
            return None
        vectors = np.asarray([row.embedding for row in rows], dtype=np.float32)
        return vectors, [row.text_hash for row in rows], [row.ability_ix for row in rows]

    def warm(self, db: Session) -> None:
        """Build the ability store now rather than on the first search.

        The store is ~3.7s to assemble, and building it lazily puts that whole
        cost on whichever visitor searches first after a boot — which on a
        scale-from-zero deployment is a real person waiting.
        """
        self._get_store(db)

    def _get_store(self, db: Session) -> _AbilityStore:
        if self._store is None:
            assert self.model_id is not None
            self._store = _build_ability_store(db, self.model_id)
        return self._store

    def _eligible_mask(
        self, db: Session, store: _AbilityStore, filters: dict[str, Any]
    ) -> FloatArray | None:
        """Which faces survive the SQL filters, as a boolean mask.

        Returns None when nothing is filtered, so the common case costs no query
        at all. The filter predicates themselves are reused from `_apply_filters`
        rather than reimplemented here, so there is one definition of what a
        colour or format filter means.
        """
        key = tuple(
            tuple(value) if isinstance(value, list) else value
            for _name, value in sorted(filters.items())
        )
        cached = self._mask_cache.get(key)
        if cached is not None:
            return cached
        if not any(
            filters.get(name) not in (None, [], "")
            for name in ("card_type", "colors", "cmc_min", "cmc_max", "format", "rarity")
        ):
            return None
        stmt = select(CardFace.oracle_id, CardFace.face_ix).join(
            Card, Card.oracle_id == CardFace.oracle_id
        )
        stmt = _apply_filters(stmt, **filters)
        mask = np.zeros(store.n_faces, dtype=bool)
        positions = store.face_pos
        for oracle_id, face_ix in db.execute(stmt):
            position = positions.get((oracle_id, face_ix))
            if position is not None:
                mask[position] = True
        # Users toggle a handful of filter combinations repeatedly, and the mask
        # only changes when the corpus does — which rebuilds this index anyway.
        if len(self._mask_cache) >= _MASK_CACHE_ENTRIES:
            self._mask_cache.clear()
        self._mask_cache[key] = mask
        return mask

    def _score(
        self,
        db: Session,
        seed_vectors: FloatArray,
        limit: int,
        *,
        bidirectional: bool,
        exclude: tuple[str, int] | None = None,
        seed_hashes: Sequence[str] | None = None,
        reject_vectors: FloatArray | None = None,
        card_type: list[str] | None = None,
        colors: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        format: list[str] | None = None,
        rarity: list[str] | None = None,
        color_feature: str = "identity",
        match_mode: str = "at_least",
    ) -> list[SimilarityHit]:
        """Score every eligible face against the seed. Nothing is truncated.

        The scoring is a Chamfer mean over ability sets:

        * forward  = mean over SEED abilities of their best match on this face
                     — "how much of the seed does this card cover?"
        * backward = mean over this face's abilities of their best seed match
                     — "how much of this card is explained by the seed?"

        Card-to-card similarity averages both, so a card that matches one ability
        and does five unrelated things scores below one that matches throughout.
        Text search uses forward only: someone searching "draw a card when a
        creature dies" wants cards with that ability and should not see them
        demoted for also having flying.

        Both means are IDF-weighted. "Flying" sits on ~3.2k faces and matches
        itself at 1.0, so unweighted it drowns out the abilities that actually
        distinguish cards. Weighting is by frequency rather than keyword-ness,
        because common non-keyword abilities ("Enchant creature", "{T}: Add {C}.")
        swamp results just as badly.
        """
        if self.model_id is None or limit <= 0 or len(seed_vectors) == 0:
            return []
        store = self._get_store(db)
        if store.n_faces == 0:
            return []

        seed = np.ascontiguousarray(seed_vectors, dtype=np.float32)
        starts = store.starts

        # One matmul over distinct texts, then gathered onto instances. Doing it
        # in this order is the whole optimisation: 37k rows scored, not 63k.
        sims_by_instance = (store.vectors @ seed.T)[store.inst_row]

        per_seed_best = _segment_max(sims_by_instance, starts)      # (n_faces, k)
        seed_weights = self._idf_weights(db, seed_hashes) if seed_hashes is not None else None
        if seed_weights is not None and float(seed_weights.sum()) > 0.0:
            forward = (per_seed_best * seed_weights).sum(axis=1) / float(seed_weights.sum())
        else:
            forward = per_seed_best.mean(axis=1)

        instance_best = sims_by_instance.max(axis=1)                # (n_inst,)
        if bidirectional:
            weighted = np.add.reduceat(instance_best * store.inst_idf, starts)
            weights = np.add.reduceat(store.inst_idf, starts)
            scores = (forward + weighted / np.maximum(weights, 1e-9)) / 2.0
        else:
            scores = forward

        alive = np.ones(store.n_faces, dtype=bool)
        if exclude is not None:
            position = store.face_pos.get(exclude)
            if position is not None:
                alive[position] = False
        mask = self._eligible_mask(
            db,
            store,
            {
                "card_type": card_type, "colors": colors, "cmc_min": cmc_min,
                "cmc_max": cmc_max, "format": format, "rarity": rarity,
                "color_feature": color_feature, "match_mode": match_mode,
            },
        )
        if mask is not None:
            alive &= mask

        if reject_vectors is not None and len(reject_vectors):
            rejected = np.ascontiguousarray(reject_vectors, dtype=np.float32)
            rejection = _segment_max(
                (store.vectors @ rejected.T)[store.inst_row].max(axis=1), starts
            )
            # Scale rather than subtract, so the score stays in [0, 1] and still
            # reads as a percentage. The scale reaches zero exactly where the hard
            # drop begins, so the two are continuous.
            scores = scores * (
                1.0
                - np.clip(
                    (rejection - _REJECT_IGNORE_SIMILARITY)
                    / (_REJECT_EXCLUDE_SIMILARITY - _REJECT_IGNORE_SIMILARITY),
                    0.0,
                    1.0,
                )
            )
            alive &= rejection < _REJECT_EXCLUDE_SIMILARITY

        candidates = np.flatnonzero(alive)
        if candidates.size == 0:
            return []
        candidate_scores = scores[candidates]
        wanted = min(limit, candidates.size)
        # argpartition then sort only the winners: O(n) instead of sorting 34k.
        top = np.argpartition(-candidate_scores, wanted - 1)[:wanted]
        top = top[np.argsort(-candidate_scores[top], kind="stable")]

        hits: list[SimilarityHit] = []
        for position in candidates[top]:
            hits.append(
                SimilarityHit(
                    face_key=store.face_keys[position],
                    score=round(float(scores[position]), 6),
                    matched_ability=self._display_ability(store, instance_best, int(position)),
                )
            )
        return hits

    @staticmethod
    def _display_ability(
        store: _AbilityStore, instance_best: FloatArray, position: int
    ) -> str | None:
        """Which ability to SHOW: relevance gates, distinctiveness breaks ties.

        Raw argmax always reports "Flying" for fliers, since a keyword self-match
        is ~1.0; a pure IDF argmax overcorrects and reports the most obscure
        ability even when it barely matched. So keep the abilities that matched
        about as well as the best one, then among those prefer the most
        distinctive. Computed only for the faces actually returned.
        """
        start, end = int(store.starts[position]), int(store.ends[position])
        if end <= start:
            return None
        segment = instance_best[start:end]
        eligible = segment >= (float(segment.max()) - _DISPLAY_SIMILARITY_MARGIN)
        ranked = np.where(eligible, store.inst_idf[start:end], -np.inf)
        return store.inst_text[start + int(np.argmax(ranked))] or None


# ---------------------------------------------------------------------------
# Module accessor
# ---------------------------------------------------------------------------


def get_semantic_index() -> SemanticIndex | None:
    global _index, _last_refresh_check, _loaded_model_id, _loaded_data_version

    # Fast path: if index is loaded and poll interval hasn't elapsed, skip refresh check
    now = time.monotonic()
    poll_seconds = max(0.0, semantic_active_model_poll_seconds())
    if _index is not None and now - _last_refresh_check < poll_seconds:
        return _index

    # Check DB for active model ID — no lock held during network I/O
    try:
        with SessionLocal() as db:
            active_model_id = get_active_semantic_model_id(db)
            data_version = get_semantic_data_version(db)
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
        if (
            _index is not None
            and _loaded_model_id is not _UNSET
            and _loaded_model_id == active_model_id
            and _loaded_data_version == data_version
        ):
            return _index
        if _index is not None and _loaded_data_version != data_version:
            logger.info(
                "Rebuilding semantic index: corpus changed (data version %s -> %s).",
                _loaded_data_version, data_version,
            )

    # S3 download + ONNX load happen OUTSIDE the lock
    try:
        with SessionLocal() as db:
            active_model = db.get(SemanticModel, active_model_id)
        if active_model is None:
            return _index
        model_root, _bundle_root = materialize_semantic_model(active_model)
        new_index = SemanticIndex(model_root=model_root, model_id=active_model.id)
    except Exception as exc:
        # Keep any previously-loaded index serving rather than dropping to 503 on
        # a transient S3/ONNX failure, and leave _loaded_model_id unchanged so the
        # next poll retries materialization (instead of pinning the failed model).
        logger.warning("Semantic index reload failed; keeping current index: %s", exc)
        return _index

    # Swap the index under lock — fast operation
    with _index_lock:
        _index = new_index
        _loaded_model_id = active_model_id
        _loaded_data_version = data_version
    return _index


def mark_semantic_index_stale() -> None:
    """Force the next lookup to rebuild the index and its ability store.

    Clearing `_loaded_model_id` as well as the poll timer matters: the embedding
    top-up appends rows for the model that is ALREADY active, so the id compare
    would otherwise hand back an index whose in-memory store predates the new
    abilities and cannot retrieve them.
    """
    global _last_refresh_check, _loaded_model_id
    _last_refresh_check = 0.0
    _loaded_model_id = _UNSET
