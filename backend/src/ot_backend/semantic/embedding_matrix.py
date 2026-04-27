from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.models import Card, CardFace, SemanticModelEmbedding

logger = logging.getLogger("ot_backend.semantic.embedding_matrix")

FloatArray = npt.NDArray[np.float32]
BoolArray = npt.NDArray[np.bool_]
Uint8Array = npt.NDArray[np.uint8]

# 5 colors fit in 5 bits.
COLOR_BIT: dict[str, int] = {"W": 1, "U": 2, "B": 4, "R": 8, "G": 16}

# 7 known categories fit in 7 bits. Order pinned for stable bit positions.
TYPE_CATEGORIES: tuple[str, ...] = (
    "creature",
    "instant",
    "sorcery",
    "enchantment",
    "artifact",
    "planeswalker",
    "land",
)
TYPE_BIT: dict[str, int] = {name: 1 << i for i, name in enumerate(TYPE_CATEGORIES)}

EMBED_LOAD_CHUNK = 4096


@dataclass(slots=True)
class EmbeddingMatrix:
    """In-memory snapshot of the active model's embeddings + filter side data.

    Built once per active-model swap; queries score against this matrix instead
    of round-tripping pgvector. Side data is bit-packed: ~46 MB for vectors
    plus <1 MB for filters.
    """

    face_keys: list[tuple[str, int]]
    key_to_idx: dict[tuple[str, int], int]
    vectors: FloatArray  # (N, dim), L2-normalized so cosine == dot product
    cmc: FloatArray  # (N,) NaN where unknown
    rarity: list[str | None]
    type_bits: Uint8Array  # (N,) bitmask over TYPE_CATEGORIES
    face_color_bits: Uint8Array  # (N,) bitmask over COLOR_BIT (face.colors)
    color_identity_bits: Uint8Array  # (N,) bitmask over COLOR_BIT (card.color_identity)
    legalities: dict[str, BoolArray]  # format_code -> (N,) bool

    @classmethod
    def load(cls, db: Session, model_id: str) -> "EmbeddingMatrix":
        total = db.execute(
            select(func.count())
            .select_from(SemanticModelEmbedding)
            .where(SemanticModelEmbedding.model_id == model_id)
        ).scalar_one()

        if total == 0:
            logger.warning("EmbeddingMatrix: no embeddings for model %s", model_id)
            return cls._empty()

        # Allocate up-front so we never hold per-row temporaries.
        vectors = np.empty((total, 0), dtype=np.float32)  # resized after first row
        face_keys: list[tuple[str, int]] = [("", 0)] * total
        cmc = np.full(total, np.nan, dtype=np.float32)
        rarity: list[str | None] = [None] * total
        type_bits = np.zeros(total, dtype=np.uint8)
        face_color_bits = np.zeros(total, dtype=np.uint8)
        color_identity_bits = np.zeros(total, dtype=np.uint8)
        per_row_legalities: list[dict[str, str]] = [{}] * total

        stmt = (
            select(
                SemanticModelEmbedding.oracle_id,
                SemanticModelEmbedding.face_ix,
                SemanticModelEmbedding.embedding,
                CardFace.colors,
                CardFace.type_categories,
                Card.cmc,
                Card.rarity,
                Card.color_identity,
                Card.legalities,
            )
            .join(
                CardFace,
                (CardFace.oracle_id == SemanticModelEmbedding.oracle_id)
                & (CardFace.face_ix == SemanticModelEmbedding.face_ix),
            )
            .join(Card, Card.oracle_id == SemanticModelEmbedding.oracle_id)
            .where(SemanticModelEmbedding.model_id == model_id)
            .execution_options(yield_per=EMBED_LOAD_CHUNK)
        )

        i = 0
        for row in db.execute(stmt):
            embedding = np.asarray(row.embedding, dtype=np.float32)
            if vectors.shape[1] == 0:
                vectors = np.empty((total, embedding.shape[0]), dtype=np.float32)
            vectors[i] = embedding
            face_keys[i] = (row.oracle_id, row.face_ix)
            if row.cmc is not None:
                cmc[i] = float(row.cmc)
            rarity[i] = row.rarity
            type_bits[i] = _pack_bits(row.type_categories, TYPE_BIT)
            face_color_bits[i] = _pack_bits(row.colors, COLOR_BIT)
            color_identity_bits[i] = _pack_bits(row.color_identity, COLOR_BIT)
            per_row_legalities[i] = row.legalities or {}
            i += 1

        if i != total:
            # Embedding count drifted between count() and the streamed query
            # (extremely unlikely but worth a slice rather than zero rows).
            vectors = vectors[:i]
            face_keys = face_keys[:i]
            cmc = cmc[:i]
            rarity = rarity[:i]
            type_bits = type_bits[:i]
            face_color_bits = face_color_bits[:i]
            color_identity_bits = color_identity_bits[:i]
            per_row_legalities = per_row_legalities[:i]

        _l2_normalize_inplace(vectors)

        all_formats: set[str] = set()
        for legalities in per_row_legalities:
            all_formats.update(legalities.keys())
        legalities_arr: dict[str, BoolArray] = {
            fmt: np.fromiter(
                (legalities.get(fmt) in {"legal", "restricted"} for legalities in per_row_legalities),
                count=i,
                dtype=np.bool_,
            )
            for fmt in all_formats
        }

        key_to_idx = {key: idx for idx, key in enumerate(face_keys)}

        logger.info(
            "EmbeddingMatrix ready: %d faces, dim=%d, %d legality columns",
            i,
            vectors.shape[1] if vectors.size else 0,
            len(legalities_arr),
        )
        return cls(
            face_keys=face_keys,
            key_to_idx=key_to_idx,
            vectors=vectors,
            cmc=cmc,
            rarity=rarity,
            type_bits=type_bits,
            face_color_bits=face_color_bits,
            color_identity_bits=color_identity_bits,
            legalities=legalities_arr,
        )

    @classmethod
    def _empty(cls) -> "EmbeddingMatrix":
        return cls(
            face_keys=[],
            key_to_idx={},
            vectors=np.zeros((0, 0), dtype=np.float32),
            cmc=np.zeros(0, dtype=np.float32),
            rarity=[],
            type_bits=np.zeros(0, dtype=np.uint8),
            face_color_bits=np.zeros(0, dtype=np.uint8),
            color_identity_bits=np.zeros(0, dtype=np.uint8),
            legalities={},
        )

    def __len__(self) -> int:
        return len(self.face_keys)

    def filter_mask(
        self,
        *,
        card_type: list[str] | None,
        colors: str | None,
        cmc_min: float | None,
        cmc_max: float | None,
        format: list[str] | None,
        rarity: list[str] | None,
        color_feature: str,
        match_mode: str,
    ) -> BoolArray:
        n = len(self.face_keys)
        mask = np.ones(n, dtype=np.bool_)

        if card_type:
            wanted = _bits_from_iterable(card_type, TYPE_BIT)
            if wanted:
                mask &= (self.type_bits & wanted) != 0
            else:
                # Unknown category requested → empty result.
                return np.zeros(n, dtype=np.bool_)

        wanted_colors = _bits_from_iterable(colors or (), COLOR_BIT)
        if colors is not None and wanted_colors:
            source = self.face_color_bits if color_feature == "colors" else self.color_identity_bits
            if match_mode == "exact":
                mask &= source == wanted_colors
            elif match_mode == "at_most":
                mask &= (source & ~np.uint8(wanted_colors)) == 0
            else:  # at_least
                mask &= (source & wanted_colors) == wanted_colors

        if cmc_min is not None:
            mask &= ~np.isnan(self.cmc) & (self.cmc >= cmc_min)
        if cmc_max is not None:
            mask &= ~np.isnan(self.cmc) & (self.cmc <= cmc_max)

        if format:
            fmt_mask = np.zeros(n, dtype=np.bool_)
            for fmt in format:
                column = self.legalities.get(fmt)
                if column is not None:
                    fmt_mask |= column
            mask &= fmt_mask

        if rarity:
            wanted_rarity = frozenset(rarity)
            mask &= np.fromiter(
                (r in wanted_rarity for r in self.rarity),
                count=n,
                dtype=np.bool_,
            )

        return mask


def _pack_bits(values: object, mapping: dict[str, int]) -> int:
    if not values:
        return 0
    bits = 0
    for v in values:  # pyright: ignore[reportGeneralTypeIssues]
        if isinstance(v, str):
            bit = mapping.get(v.upper() if mapping is COLOR_BIT else v.lower())
            if bit is not None:
                bits |= bit
    return bits


def _bits_from_iterable(values: object, mapping: dict[str, int]) -> int:
    if not values:
        return 0
    bits = 0
    for v in values:  # pyright: ignore[reportGeneralTypeIssues]
        if isinstance(v, str):
            bit = mapping.get(v.upper() if mapping is COLOR_BIT else v.lower())
            if bit is not None:
                bits |= bit
    return bits


def _l2_normalize_inplace(vectors: FloatArray) -> None:
    if vectors.size == 0:
        return
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    np.clip(norms, a_min=1e-12, a_max=None, out=norms)
    np.divide(vectors, norms, out=vectors)
