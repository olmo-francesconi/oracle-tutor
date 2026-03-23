from __future__ import annotations

import logging
import math
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol, TypeAlias, cast

from cachetools import TTLCache
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel
from sklearn.preprocessing import normalize
from sqlalchemy.orm import Session

from ..core.models import Card, CardFace
from .oracle_tokenizer import (
    iter_type_filters,
    make_mtg_analyzer,
    normalize_type_line,
)

logger = logging.getLogger("oracle_tutor_api.api")

# Max results kept when ranking for pagination
DEFAULT_CACHE_TOP_K = 1000
CARD_NAME_DELIMITER = "\x00\x01CARD_NAME\x01\x00"
TYPE_LINE_DELIMITER = "\x00\x01TYPE_LINE\x01\x00"
FloatArray: TypeAlias = np.ndarray[tuple[int], np.dtype[np.float64]]
IndexArray: TypeAlias = np.ndarray[tuple[int], np.dtype[np.int_]]


class SparseLike(Protocol):
    T: object

    @property
    def nnz(self) -> int: ...

    @property
    def data(self) -> FloatArray: ...

    @property
    def indices(self) -> IndexArray: ...

    def __matmul__(self, other: object, /) -> object: ...
    def __getitem__(self, key: object, /) -> object: ...
    def multiply(self, other: object, /) -> SparseLike: ...
    def sum(self, axis: int | None = None) -> object: ...
    def toarray(self) -> object: ...


AnalyzerFn: TypeAlias = Callable[[str], list[str]]


class VectorizerLike(Protocol):
    vocabulary_: dict[str, int]

    def transform(self, raw_documents: list[str]) -> object: ...
    def fit_transform(self, raw_documents: list[str]) -> object: ...
    def set_params(self, **params: object) -> object: ...


def _build_vectorizer(*, analyzer: AnalyzerFn, min_df: int, max_df: int | float) -> VectorizerLike:
    vectorizer = TfidfVectorizer(
        analyzer=analyzer,  # pyright: ignore[reportArgumentType]
        lowercase=False,
        min_df=min_df,
        max_df=max_df,
        sublinear_tf=True,
        norm=None,  # pyright: ignore[reportArgumentType]
    )
    return cast(VectorizerLike, vectorizer)


def _set_vectorizer_params(vectorizer: VectorizerLike, *, min_df: int, max_df: int | float) -> None:
    _ = vectorizer.set_params(min_df=min_df, max_df=max_df)


def _fit_transform(vectorizer: VectorizerLike, docs: list[str]) -> SparseLike:
    return cast(SparseLike, vectorizer.fit_transform(docs))


def _transform(vectorizer: VectorizerLike, docs: list[str]) -> SparseLike:
    return cast(SparseLike, vectorizer.transform(docs))


def _normalize_matrix(matrix: SparseLike) -> SparseLike:
    return cast(SparseLike, normalize(matrix, norm="l2", axis=1, copy=True))


def _vocabulary_size(vectorizer: VectorizerLike) -> int:
    return len(vectorizer.vocabulary_)


def _dense_1d(value: object) -> FloatArray:
    return cast(FloatArray, np.asarray(value).ravel())


def _dot_scores(value: object) -> FloatArray:
    try:
        return cast(FloatArray, getattr(value, "A1"))
    except Exception:
        return _dense_1d(cast(SparseLike, value).toarray())


def _squared_l2_norm(values: FloatArray) -> float:
    return float(values @ values)


def _linear_kernel_scores(seed_vec: object, matrix: SparseLike) -> FloatArray:
    kernel_scores = cast(object, linear_kernel(seed_vec, matrix))
    return _dense_1d(kernel_scores)


def _parse_colors(colors: str | None) -> set[str]:
    if not colors:
        return set()
    # Accept things like "W,U" or "WUBRG"
    cleaned = colors.replace(",", "").replace(" ", "").upper()
    return {c for c in cleaned if c in {"W", "U", "B", "R", "G"}}


CacheKey = tuple[
    str,
    str | None,
    str | None,
    str | None,
    float | None,
    float | None,
    str | None,
    str,
    str,
]


@dataclass
class TfidfIndex:
    vectorizer: VectorizerLike
    matrix_raw: SparseLike  # scipy sparse matrix, NOT normalized (norm=None)
    matrix_l2: SparseLike  # scipy sparse matrix, L2-normalized rows
    face_ids: list[int]
    face_id_to_idx: dict[int, int]
    face_card_ids: list[str]
    face_names: list[str]
    face_type_lines_lower: list[str]
    face_colors: list[set[str]]
    face_color_identities: list[set[str]]
    face_legalities: list[dict[str, str]]
    face_cmcs: list[float]
    face_rarities: list[str]
    built_at: float

    # cache key: (query_or_seed, card_type, colors, format, cmc_min, cmc_max, rarity, match_mode, color_feature)
    cache: TTLCache[CacheKey, list[tuple[int, float]]]

    def _filter_mask(
        self,
        *,
        exclude_card_id: str | None,
        card_type: str | None,
        colors: str | None,
        format: str | None,
        cmc_min: float | None,
        cmc_max: float | None,
        rarity: str | None,
        match_mode: str = "at_least",  # "at_least", "at_most", or "exact"
        color_feature: str = "identity",  # "identity" or "colors"
    ) -> list[bool]:
        type_filters = list(iter_type_filters(card_type))
        # Handle colorless logic: if colors="C" (or similar indicator) treat as empty set
        is_colorless_search = colors == "C"
        want_colors: set[str] = set() if is_colorless_search else _parse_colors(colors)

        mask: list[bool] = [True] * len(self.face_ids)
        for i in range(len(mask)):
            if exclude_card_id and self.face_card_ids[i] == exclude_card_id:
                mask[i] = False
                continue
            if type_filters:
                tl = self.face_type_lines_lower[i]
                if not any(t in tl for t in type_filters):
                    mask[i] = False
                    continue
            
            # Color filtering
            if color_feature == "colors":
                face_c = self.face_colors[i]
            else:
                face_c = self.face_color_identities[i]

            if is_colorless_search:
                # Must be strictly colorless
                if len(face_c) > 0:
                    mask[i] = False
                    continue
            elif want_colors:
                if match_mode == "exact":
                    # Exact Match: Must match colors exactly (e.g. W+G means exactly Selesnya).
                    if face_c != want_colors:
                        mask[i] = False
                        continue
                elif match_mode == "at_most":
                    # At Most: Card colors must be a subset of query colors.
                    # e.g. Query WBR -> Shows W, WB, WR, WBR. Hides WBG.
                    if not face_c.issubset(want_colors):
                        mask[i] = False
                        continue
                else:
                    # At Least (default): Card must contain at least these colors.
                    # e.g. Query WB -> Shows WB, WBG, WBR. Hides W.
                    if not want_colors.issubset(face_c):
                        mask[i] = False
                        continue

            if format:
                # legalities is a dict like {"commander": "legal", "modern": "banned"}
                # we want "legal" or "restricted"
                legality = self.face_legalities[i].get(format, "not_legal")
                if legality not in ("legal", "restricted"):
                    mask[i] = False
                    continue
            if cmc_min is not None:
                if self.face_cmcs[i] < cmc_min:
                    mask[i] = False
                    continue
            if cmc_max is not None:
                if self.face_cmcs[i] > cmc_max:
                    mask[i] = False
                    continue
            if rarity:
                if self.face_rarities[i] != rarity:
                    mask[i] = False
                    continue
        return mask

    def _rank(
        self,
        scores: Iterable[float],
        *,
        mask: list[bool],
        top_k: int,
    ) -> list[tuple[int, float]]:
        # scores is a 1D numpy array-like
        candidates: list[tuple[int, float]] = []
        for i, s in enumerate(scores):
            if not mask[i]:
                continue
            if s <= 0:
                continue
            candidates.append((i, float(s)))

        # Sort by score desc, then face_name asc for stability
        candidates.sort(key=lambda t: (-t[1], self.face_names[t[0]].lower()))
        return candidates[:top_k]

    def search(
        self,
        *,
        query: str,
        limit: int,
        offset: int,
        card_type: str | None = None,
        colors: str | None = None,
        format: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        rarity: str | None = None,
        match_mode: str = "at_least",
        color_feature: str = "identity",
        cache_top_k: int = DEFAULT_CACHE_TOP_K,
    ) -> list[tuple[int, float]]:
        if not self.face_ids:
            return []
        q = (query or "").strip()
        if not q:
            return []

        cache_key = (f"q:{q}", card_type, colors, format, cmc_min, cmc_max, rarity, match_mode, color_feature)
        if cache_key in self.cache:
            cached = self.cache[cache_key]
        else:
            # Match-only cosine similarity:
            # - dot uses full vectors (query has only its own terms)
            # - doc norm only considers query term dimensions, so extra oracle text doesn't penalize.
            q_vec = _transform(self.vectorizer, [q])
            if q_vec.nnz == 0:
                logger.warning("Query '%s' produced no tokens in vocabulary", q)
                return []

            matrix_raw = self.matrix_raw
            dot = (q_vec @ matrix_raw.T)
            dot_scores = _dot_scores(dot)

            q_norm = math.sqrt(_squared_l2_norm(q_vec.data))
            if q_norm <= 0:
                return []

            q_term_idx = q_vec.indices
            if q_term_idx.size == 0:
                return []

            docs_q = cast(SparseLike, matrix_raw[:, q_term_idx])
            doc_match_sq = docs_q.multiply(docs_q).sum(axis=1)
            doc_match_norm = cast(FloatArray, np.sqrt(_dense_1d(doc_match_sq)))

            denom = q_norm * doc_match_norm
            scores = np.zeros_like(dot_scores, dtype=float)
            ok = denom > 0
            scores[ok] = dot_scores[ok] / denom[ok]
            mask = self._filter_mask(
                exclude_card_id=None,
                card_type=card_type,
                colors=colors,
                format=format,
                cmc_min=cmc_min,
                cmc_max=cmc_max,
                rarity=rarity,
                match_mode=match_mode,
                color_feature=color_feature,
            )
            ranked = self._rank(scores, mask=mask, top_k=cache_top_k)
            cached = [(self.face_ids[i], s) for i, s in ranked]
            self.cache[cache_key] = cached

        return cached[offset : offset + limit]

    def similar(
        self,
        *,
        seed_face_id: int,
        exclude_card_id: str,
        limit: int,
        offset: int,
        card_type: str | None = None,
        colors: str | None = None,
        format: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        rarity: str | None = None,
        match_mode: str = "at_least",
        color_feature: str = "identity",
        cache_top_k: int = DEFAULT_CACHE_TOP_K,
    ) -> list[tuple[int, float]]:
        if not self.face_ids:
            return []
        cache_key = (f"similar:{seed_face_id}", card_type, colors, format, cmc_min, cmc_max, rarity, match_mode, color_feature)
        if cache_key in self.cache:
            cached = self.cache[cache_key]
        else:
            seed_idx = self.face_id_to_idx.get(seed_face_id)
            if seed_idx is None:
                return []

            matrix_l2 = self.matrix_l2
            seed_vec = matrix_l2[seed_idx]
            scores = _linear_kernel_scores(seed_vec, matrix_l2)

            mask = self._filter_mask(
                exclude_card_id=exclude_card_id,
                card_type=card_type,
                colors=colors,
                format=format,
                cmc_min=cmc_min,
                cmc_max=cmc_max,
                rarity=rarity,
                match_mode=match_mode,
                color_feature=color_feature,
            )
            # Also exclude the seed face itself.
            mask[seed_idx] = False

            ranked = self._rank(scores, mask=mask, top_k=cache_top_k)
            cached = [(self.face_ids[i], s) for i, s in ranked]
            self.cache[cache_key] = cached

        return cached[offset : offset + limit]


def build_tfidf_index(db: Session) -> TfidfIndex:
    """
    Build a TF-IDF index from all CardFaces in the DB.

    This is in-memory and rebuilt on startup (or when explicitly refreshed).
    """
    started = time.perf_counter()

    rows = cast(
        list[
            tuple[
                int,
                str,
                str | None,
                str | None,
                str | None,
                list[str] | None,
                list[str] | None,
                str,
                dict[str, str] | None,
                float | None,
                str | None,
            ]
        ],
        db.query(
            CardFace.id,
            CardFace.card_id,
            CardFace.name,
            CardFace.type_line,
            CardFace.oracle_text,
            CardFace.colors,
            Card.color_identity,
            Card.name.label("card_name"),
            Card.legalities,
            Card.cmc,
            Card.rarity,
        )
        .join(Card, CardFace.card_id == Card.id)
        .all(),
    )

    face_ids: list[int] = []
    face_card_ids: list[str] = []
    face_names: list[str] = []
    face_type_lines_lower: list[str] = []
    face_colors: list[set[str]] = []
    face_color_identities: list[set[str]] = []
    face_legalities: list[dict[str, str]] = []
    face_cmcs: list[float] = []
    face_rarities: list[str] = []
    docs: list[str] = []

    for (
        face_id,
        card_id,
        face_name,
        type_line,
        oracle_text,
        colors,
        color_identity,
        _card_name,
        legalities,
        cmc,
        rarity,
    ) in rows:
        face_ids.append(int(face_id))
        face_card_ids.append(str(card_id))
        face_names.append(face_name or "")
        tl_norm = normalize_type_line(type_line)
        face_type_lines_lower.append((tl_norm or "").lower())
        face_colors.append(set(colors or []))
        face_color_identities.append(set(color_identity or []))
        face_legalities.append(legalities or {})
        face_cmcs.append(float(cmc or 0.0))
        face_rarities.append(rarity or "")

        oracle_doc = oracle_text or ""
        if face_name:
            oracle_doc = oracle_doc + CARD_NAME_DELIMITER + face_name
        if type_line:
            oracle_doc = oracle_doc + TYPE_LINE_DELIMITER + type_line
        docs.append(oracle_doc)

    def _parse_max_df(raw: str) -> int | float:
        """
        sklearn allows max_df as either:
        - float in (0, 1] meaning "proportion of docs"
        - int meaning "absolute document count"

        If we always parse as float, env like "2" becomes 2.0 (not an int),
        which can behave surprisingly. Keep ints as ints when possible.
        """
        s = (raw or "").strip()
        if not s:
            return 0.98
        try:
            # Treat scientific notation / decimals as float.
            if any(ch in s for ch in (".", "e", "E")):
                return float(s)
            return int(s)
        except Exception:
            # Fall back to float parsing to preserve current behavior.
            return float(s)

    def _sanitize_df(min_df_in: int, max_df_in: int | float, n_docs: int) -> tuple[int, int | float]:
        """
        Prevent sklearn's: "max_df corresponds to < documents than min_df"
        This commonly happens on first boot when there are 0-1 docs.
        """
        # Always keep min_df in [1, n_docs] when we have docs (and at least 1 otherwise).
        if n_docs <= 0:
            return 1, 1.0

        min_df_out = max(1, int(min_df_in))
        if min_df_out > n_docs:
            min_df_out = n_docs

        max_df_out: int | float = max_df_in
        # Normalize "percentage" max_df that becomes 0 docs for tiny corpora.
        if isinstance(max_df_out, float) and 0.0 < max_df_out <= 1.0:
            # With n_docs=1 and max_df=0.98, sklearn effectively gets max_docs=0.
            # Force it to allow at least 1 doc.
            if n_docs == 1:
                max_df_out = 1.0
            else:
                # If max_df would correspond to fewer docs than min_df, relax max_df.
                # We don't try to perfectly mirror sklearn rounding; we just avoid the invalid case.
                if (max_df_out * n_docs) < float(min_df_out):
                    max_df_out = 1.0
        else:
            # Absolute max_df: clamp to [min_df, n_docs]
            try:
                max_df_int = int(max_df_out)
                if max_df_int < min_df_out:
                    max_df_int = min_df_out
                if max_df_int > n_docs:
                    max_df_int = n_docs
                max_df_out = max_df_int
            except Exception:
                # If it's some weird value, just allow everything.
                max_df_out = 1.0

        return min_df_out, max_df_out

    min_df_env = int(os.getenv("TFIDF_MIN_DF", "1"))
    max_df_env = _parse_max_df(os.getenv("TFIDF_MAX_DF", "0.98"))

    analyzer: AnalyzerFn = make_mtg_analyzer((1, 2))
    vectorizer = _build_vectorizer(analyzer=analyzer, min_df=1, max_df=1.0)
    # Keep 1 doc per face. If a doc is empty/untokenizable, use a placeholder so indices align.
    if not docs:
        docs = ["__empty__"]
    docs_aligned = [d if (d and d.strip()) else "__empty__" for d in docs]
    min_df, max_df = _sanitize_df(min_df_env, max_df_env, n_docs=len(docs_aligned))
    _set_vectorizer_params(vectorizer, min_df=min_df, max_df=max_df)

    try:
        matrix_raw = _fit_transform(vectorizer, docs_aligned)
    except ValueError as e:
        # e.g. "empty vocabulary; perhaps the documents only contain stop words"
        logger.warning(
            "TF-IDF fit failed (%s). Falling back to safe empty index (min_df=1, max_df=1.0).",
            e,
        )
        safe_vectorizer = _build_vectorizer(analyzer=analyzer, min_df=1, max_df=1.0)
        vectorizer = safe_vectorizer
        matrix_raw = _fit_transform(vectorizer, ["__empty__"])

    matrix_l2 = _normalize_matrix(matrix_raw)

    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "TF-IDF index built: %d faces, %d features, %.2f ms",
        len(face_ids),
        _vocabulary_size(vectorizer),
        elapsed_ms,
    )

    face_id_to_idx = {face_id: i for i, face_id in enumerate(face_ids)}
    return TfidfIndex(
        vectorizer=vectorizer,
        matrix_raw=matrix_raw,
        matrix_l2=matrix_l2,
        face_ids=face_ids,
        face_id_to_idx=face_id_to_idx,
        face_card_ids=face_card_ids,
        face_names=face_names,
        face_type_lines_lower=face_type_lines_lower,
        face_colors=face_colors,
        face_color_identities=face_color_identities,
        face_legalities=face_legalities,
        face_cmcs=face_cmcs,
        face_rarities=face_rarities,
        built_at=time.time(),
        cache=TTLCache(
            maxsize=int(os.getenv("ORACLE_TUTOR_API_TFIDF_CACHE_MAXSIZE", "100")),
            ttl=int(os.getenv("ORACLE_TUTOR_API_TFIDF_CACHE_TTL", "600")),
        ),
    )
