from __future__ import annotations

import json
import logging
import threading
import time
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any
from typing import cast as type_cast

import numpy as np
import numpy.typing as npt
from sqlalchemy import and_, cast, func, or_, select, tuple_
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

_VALID_COLORS = frozenset({"W", "U", "B", "R", "G"})

# Two-stage retrieval knobs. Stage 1 scans distinct ability vectors exactly
# (~37k rows, no HNSW — see migration 0006) and keeps the closest `_ABILITY_PROBE`
# of them; those expand to at most `_CANDIDATE_FACES_PER_ABILITY` faces, which
# stage 2 rescores. Generous enough that the candidate set is not the binding
# constraint on result quality for realistic `limit` values.
_ABILITY_PROBE = 256
_CANDIDATE_FACES_PER_ABILITY = 400
# How far below the best-matching ability another ability may sit and still be
# considered "matched just as well" when picking which one to show the user.
_DISPLAY_SIMILARITY_MARGIN = 0.05
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


def _weighted_mean(values: FloatArray, weights: FloatArray | None) -> float:
    if weights is None or float(weights.sum()) <= 0.0:
        return float(values.mean())
    return float((values * weights).sum() / weights.sum())


def _chamfer_rerank(
    seed_vectors: FloatArray,
    candidate_vectors: FloatArray,
    *,
    bidirectional: bool,
    seed_weights: FloatArray | None = None,
    candidate_weights: FloatArray | None = None,
) -> tuple[float, int]:
    """Score two ability sets and report which candidate ability matched best.

    Stored vectors are already L2-normalized, so the dot product is cosine
    similarity and `sims[i, j]` is seed ability i against candidate ability j.

    * forward  = mean over seed abilities of their best candidate match
                 — "how much of the seed does this card cover?"
    * backward = mean over candidate abilities of their best seed match
                 — "how much of this card is explained by the seed?"

    Card-to-card similarity averages both, so a card that matches one ability
    and does five unrelated things scores below one that matches throughout.
    Text search uses forward only (see `search_oracle`).

    Both means are IDF-weighted: "Flying" sits on ~3.2k faces and matches itself
    at 1.0, so unweighted it drowns out the abilities that actually distinguish
    cards. Weighting is by frequency rather than by keyword-ness because common
    non-keyword abilities ("Enchant creature", "{T}: Add {C}.") swamp results
    just as badly.
    """
    sims = seed_vectors @ candidate_vectors.T
    forward = _weighted_mean(sims.max(axis=1), seed_weights)
    if bidirectional:
        backward = _weighted_mean(sims.max(axis=0), candidate_weights)
        score = (forward + backward) / 2.0
    else:
        score = forward

    # Choosing the ability to SHOW the user: relevance gates, distinctiveness
    # only breaks ties. Raw argmax always reports "Flying" for fliers (a keyword
    # self-match is ~1.0); pure IDF-weighted argmax overcorrects and reports the
    # most obscure ability instead, even when it barely matched. So: keep the
    # abilities that matched about as well as the best one, then among those
    # prefer the most distinctive.
    per_candidate_best = sims.max(axis=0)
    if candidate_weights is None:
        return score, int(np.argmax(per_candidate_best))
    eligible = per_candidate_best >= (float(per_candidate_best.max()) - _DISPLAY_SIMILARITY_MARGIN)
    tiebreak = np.where(eligible, candidate_weights, -np.inf)
    return score, int(np.argmax(tiebreak))


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


class SemanticIndex:
    model: OnnxTextEncoder
    model_id: str | None
    # Class-level default, not just an __init__ assignment: callers construct
    # this via object.__new__ to get a DB-only index without loading ONNX.
    _idf: dict[str, float] | None = None

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
        ignore_keywords: bool = False,
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
        default = self._load_face_abilities(db, face_key, ignore_keywords=ignore_keywords)
        if default is None:
            # Every ability was a keyword and keywords were excluded: there is
            # nothing left to match on, so return nothing rather than garbage.
            return []
        default_ixs = default[2]

        if include_abilities:
            # Loaded by index alone: an explicit pick overrides ignore_keywords.
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
            ignore_keywords=ignore_keywords,
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
        ignore_keywords: bool = False,
    ) -> list[SimilarityHit]:
        """Find faces that *have* an ability matching the query text.

        Deliberately max-pooled rather than bidirectional: someone searching
        "draw a card when a creature dies" wants cards with that ability, and
        should not see them demoted for also having flying and four other
        abilities the query never mentioned.
        """
        if self.model_id is None:
            return []
        query_vec = np.asarray([self.encode_query(query)], dtype=np.float32)
        return self._score(
            db,
            query_vec,
            limit,
            bidirectional=False,
            ignore_keywords=ignore_keywords,
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
        ignore_keywords: bool = False,
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
            # A hand-picked subset overrides the keyword filter: the user named
            # these abilities explicitly.
            stmt = stmt.where(CardFaceAbility.ability_ix.in_(list(ability_ixs)))
        elif ignore_keywords:
            stmt = stmt.where(CardFaceAbility.is_keyword.is_(False))
        rows = db.execute(stmt.order_by(CardFaceAbility.ability_ix)).all()
        if not rows:
            return None
        vectors = np.asarray([row.embedding for row in rows], dtype=np.float32)
        return vectors, [row.text_hash for row in rows], [row.ability_ix for row in rows]

    def _candidate_faces(
        self,
        db: Session,
        seed_vectors: FloatArray,
        *,
        exclude: tuple[str, int] | None,
        filters: dict[str, Any],
        ignore_keywords: bool,
    ) -> list[tuple[tuple[str, int], float]]:
        """Stage 1: cheap per-ability kNN, unioned across the seed's abilities.

        Ranking each ability's neighbours by DISTINCT ability text (rather than
        by face) is what makes this useful: one probe returns 256 different
        abilities instead of 256 copies of "flying" from 256 different cards.
        """
        best: dict[tuple[str, int], float] = {}
        for seed_vector in seed_vectors:
            distance = SemanticAbilityEmbedding.embedding.cosine_distance(list(seed_vector))
            nearest = (
                select(
                    SemanticAbilityEmbedding.text_hash.label("text_hash"),
                    (1.0 - distance).label("sim"),
                )
                .where(SemanticAbilityEmbedding.model_id == self.model_id)
                .order_by(distance)
                .limit(_ABILITY_PROBE)
                .cte("nearest_abilities")
            )

            stmt = (
                select(
                    CardFaceAbility.oracle_id,
                    CardFaceAbility.face_ix,
                    func.max(nearest.c.sim).label("sim"),
                )
                .select_from(nearest)
                .join(CardFaceAbility, CardFaceAbility.text_hash == nearest.c.text_hash)
                .join(
                    CardFace,
                    and_(
                        CardFace.oracle_id == CardFaceAbility.oracle_id,
                        CardFace.face_ix == CardFaceAbility.face_ix,
                    ),
                )
                .join(Card, Card.oracle_id == CardFaceAbility.oracle_id)
            )
            if ignore_keywords:
                stmt = stmt.where(CardFaceAbility.is_keyword.is_(False))
            if exclude is not None:
                stmt = stmt.where(
                    or_(
                        CardFaceAbility.oracle_id != exclude[0],
                        CardFaceAbility.face_ix != exclude[1],
                    )
                )
            stmt = _apply_filters(stmt, **filters)
            stmt = (
                stmt.group_by(CardFaceAbility.oracle_id, CardFaceAbility.face_ix)
                .order_by(func.max(nearest.c.sim).desc())
                .limit(_CANDIDATE_FACES_PER_ABILITY)
            )

            for row in db.execute(stmt).all():
                key = (row.oracle_id, row.face_ix)
                sim = float(row.sim)
                if sim > best.get(key, -1.0):
                    best[key] = sim
        return sorted(best.items(), key=lambda item: item[1], reverse=True)

    def _load_candidate_abilities(
        self, db: Session, face_keys: list[tuple[str, int]], *, ignore_keywords: bool
    ) -> dict[tuple[str, int], tuple[FloatArray, list[str], list[str]]]:
        """Return (vectors, display texts, text hashes) per candidate face."""
        if not face_keys:
            return {}
        stmt = (
            select(
                CardFaceAbility.oracle_id,
                CardFaceAbility.face_ix,
                CardFaceAbility.text,
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
            .where(tuple_(CardFaceAbility.oracle_id, CardFaceAbility.face_ix).in_(face_keys))
        )
        if ignore_keywords:
            stmt = stmt.where(CardFaceAbility.is_keyword.is_(False))
        rows = db.execute(
            stmt.order_by(
                CardFaceAbility.oracle_id, CardFaceAbility.face_ix, CardFaceAbility.ability_ix
            )
        ).all()

        grouped: dict[tuple[str, int], tuple[list[list[float]], list[str], list[str]]] = {}
        for row in rows:
            vectors, texts, hashes = grouped.setdefault((row.oracle_id, row.face_ix), ([], [], []))
            vectors.append(row.embedding)
            texts.append(row.text)
            hashes.append(row.text_hash)
        return {
            key: (np.asarray(vectors, dtype=np.float32), texts, hashes)
            for key, (vectors, texts, hashes) in grouped.items()
        }

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
        ignore_keywords: bool = False,
        card_type: list[str] | None = None,
        colors: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        format: list[str] | None = None,
        rarity: list[str] | None = None,
        color_feature: str = "identity",
        match_mode: str = "at_least",
    ) -> list[SimilarityHit]:
        if self.model_id is None or limit <= 0 or len(seed_vectors) == 0:
            return []

        filters: dict[str, Any] = {
            "card_type": card_type,
            "colors": colors,
            "cmc_min": cmc_min,
            "cmc_max": cmc_max,
            "format": format,
            "rarity": rarity,
            "color_feature": color_feature,
            "match_mode": match_mode,
        }
        candidates = self._candidate_faces(
            db, seed_vectors, exclude=exclude, filters=filters, ignore_keywords=ignore_keywords
        )
        if not candidates:
            return []

        candidate_keys = [key for key, _ in candidates]
        ability_map = self._load_candidate_abilities(db, candidate_keys, ignore_keywords=ignore_keywords)

        # A free-text query is one vector with no corpus frequency of its own,
        # so only the candidate side is IDF-weighted there.
        seed_weights = self._idf_weights(db, seed_hashes) if seed_hashes is not None else None

        hits: list[SimilarityHit] = []
        for key in candidate_keys:
            entry = ability_map.get(key)
            if entry is None:
                continue
            candidate_vectors, candidate_texts, candidate_hashes = entry

            reject_scale = 1.0
            if reject_vectors is not None and len(reject_vectors):
                reject_sim = float((reject_vectors @ candidate_vectors.T).max())
                if reject_sim >= _REJECT_EXCLUDE_SIMILARITY:
                    continue
                reject_scale = 1.0 - max(
                    0.0,
                    (reject_sim - _REJECT_IGNORE_SIMILARITY)
                    / (_REJECT_EXCLUDE_SIMILARITY - _REJECT_IGNORE_SIMILARITY),
                )

            score, matched_ix = _chamfer_rerank(
                seed_vectors,
                candidate_vectors,
                bidirectional=bidirectional,
                seed_weights=seed_weights,
                candidate_weights=self._idf_weights(db, candidate_hashes),
            )
            # Scale rather than subtract, so the score stays in [0, 1] and still
            # reads as a percentage in the UI. Cards clear of the rejected
            # ability keep their score untouched; the scale reaches zero exactly
            # where the hard drop begins, so the two are continuous.
            score *= reject_scale
            hits.append(
                SimilarityHit(
                    face_key=key,
                    score=round(score, 6),
                    matched_ability=candidate_texts[matched_ix] or None,
                )
            )

        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:limit]


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
        # Keep any previously-loaded index serving rather than dropping to 503 on
        # a transient S3/ONNX failure, and leave _loaded_model_id unchanged so the
        # next poll retries materialization (instead of pinning the failed model).
        logger.warning("Semantic index reload failed; keeping current index: %s", exc)
        return _index

    # Swap the index under lock — fast operation
    with _index_lock:
        _index = new_index
        _loaded_model_id = active_model_id
    return _index


def mark_semantic_index_stale() -> None:
    global _last_refresh_check
    _last_refresh_check = 0.0
