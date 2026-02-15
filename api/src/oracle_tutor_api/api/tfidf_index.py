from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Tuple, cast

from cachetools import TTLCache
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel
from sklearn.preprocessing import normalize
from sqlalchemy.orm import Session

from ..core.models import Card, CardFace
from .oracle_tokenizer import (
    _CARD_NAME_DELIMITER,
    _TYPE_LINE_DELIMITER,
    iter_type_filters,
    make_mtg_analyzer,
    normalize_type_line,
)

logger = logging.getLogger("oracle_tutor_api.api")


def _parse_colors(colors: str | None) -> set[str]:
    if not colors:
        return set()
    # Accept things like "W,U" or "WUBRG"
    cleaned = colors.replace(",", "").replace(" ", "").upper()
    return {c for c in cleaned if c in {"W", "U", "B", "R", "G"}}


@dataclass
class TfidfIndex:
    vectorizer: TfidfVectorizer
    matrix_raw: Any  # scipy sparse matrix, NOT normalized (norm=None)
    matrix_l2: Any  # scipy sparse matrix, L2-normalized rows
    face_ids: List[int]
    face_id_to_idx: dict[int, int]
    face_card_ids: List[str]
    face_names: List[str]
    face_type_lines_lower: List[str]
    face_colors: List[set[str]]
    face_color_identities: List[set[str]]
    face_legalities: List[dict]
    face_cmcs: List[float]
    face_rarities: List[str]
    built_at: float

    # cache key: (query_or_seed, card_type, colors, format, cmc_min, cmc_max, rarity, match_mode) -> List[(face_id, score)]
    cache: TTLCache

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
    ) -> List[bool]:
        type_filters = list(iter_type_filters(card_type))
        # Handle colorless logic: if colors="C" (or similar indicator) treat as empty set
        is_colorless_search = colors == "C"
        want_colors = set() if is_colorless_search else _parse_colors(colors)

        mask: List[bool] = [True] * len(self.face_ids)
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
        scores,
        *,
        mask: List[bool],
        top_k: int,
    ) -> List[Tuple[int, float]]:
        # scores is a 1D numpy array-like
        candidates: List[Tuple[int, float]] = []
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
        cache_top_k: int = 1000,
    ) -> List[Tuple[int, float]]:
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
            q_vec = cast(Any, self.vectorizer.transform([q]))
            logger.debug("Query: '%s', tokens: %s", q, self.vectorizer.inverse_transform(q_vec))
            if q_vec.nnz == 0:
                logger.warning("Query '%s' produced no tokens in vocabulary", q)
                return []

            matrix_raw = cast(Any, self.matrix_raw)
            dot = (q_vec @ matrix_raw.T)
            try:
                dot_scores = dot.A1  # (n_docs,)
            except Exception:
                dot_scores = np.asarray(dot.toarray()).ravel()

            q_norm = float(np.sqrt(np.sum(np.square(q_vec.data))))
            if q_norm <= 0:
                return []

            q_term_idx = q_vec.indices
            if q_term_idx.size == 0:
                return []

            docs_q = matrix_raw[:, q_term_idx]
            doc_match_sq = docs_q.multiply(docs_q).sum(axis=1)
            doc_match_norm = np.sqrt(np.asarray(doc_match_sq).ravel())

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
        cache_top_k: int = 1000,
    ) -> List[Tuple[int, float]]:
        if not self.face_ids:
            return []
        cache_key = (f"similar:{seed_face_id}", card_type, colors, format, cmc_min, cmc_max, rarity, match_mode, color_feature)
        if cache_key in self.cache:
            cached = self.cache[cache_key]
        else:
            seed_idx = self.face_id_to_idx.get(seed_face_id)
            if seed_idx is None:
                return []

            matrix_l2 = cast(Any, self.matrix_l2)
            seed_vec = matrix_l2[seed_idx]
            
            # Debug: what tokens are in the seed vector?
            seed_tokens = self.vectorizer.inverse_transform(seed_vec)
            logger.debug("Seed face_id %d (%s) tokens: %s", seed_face_id, self.face_names[seed_idx], seed_tokens)
            
            scores = linear_kernel(seed_vec, matrix_l2).ravel()
            
            # Debug: top scores before filtering
            top_raw_idx = np.argsort(scores)[-5:][::-1]
            logger.debug("Top raw similarities: %s", [(self.face_names[idx], scores[idx]) for idx in top_raw_idx])

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

    rows = (
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
        .all()
    )

    face_ids: List[int] = []
    face_card_ids: List[str] = []
    face_names: List[str] = []
    face_type_lines_lower: List[str] = []
    face_colors: List[set[str]] = []
    face_color_identities: List[set[str]] = []
    face_legalities: List[dict] = []
    face_cmcs: List[float] = []
    face_rarities: List[str] = []
    docs: List[str] = []

    for (
        face_id,
        card_id,
        face_name,
        type_line,
        oracle_text,
        colors,
        color_identity,
        card_name,
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

        # Pass oracle_text with card_name (face_name) and type_line for tokenization
        # Use face_name as it's the name on the card face, which is what appears in oracle text
        oracle_doc = oracle_text or ""
        if face_name:
            oracle_doc = oracle_doc + _CARD_NAME_DELIMITER + face_name
        if type_line:
            oracle_doc = oracle_doc + _TYPE_LINE_DELIMITER + type_line
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

    min_df_env = int(os.getenv("TFIDF_MIN_DF", "2"))
    max_df_env = _parse_max_df(os.getenv("TFIDF_MAX_DF", "0.98"))

    vectorizer = TfidfVectorizer(
        # sklearn stubs used by Pyright can be overly strict here; at runtime a callable analyzer is valid.
        analyzer=cast(Any, make_mtg_analyzer((1, 2))),
        lowercase=False,  # we lowercase in tokenizer
        min_df=1,  # will be overwritten after docs are aligned
        max_df=1.0,  # will be overwritten after docs are aligned
        sublinear_tf=True,
        norm=cast(Any, None),  # normalize explicitly so oracle search can use match-only norms
    )
    # Keep 1 doc per face. If a doc is empty/untokenizable, use a placeholder so indices align.
    if not docs:
        docs = ["__empty__"]
    docs_aligned = [d if (d and d.strip()) else "__empty__" for d in docs]
    min_df, max_df = _sanitize_df(min_df_env, max_df_env, n_docs=len(docs_aligned))
    vectorizer.set_params(min_df=min_df, max_df=max_df)

    try:
        matrix_raw = vectorizer.fit_transform(docs_aligned)
    except ValueError as e:
        # e.g. "empty vocabulary; perhaps the documents only contain stop words"
        logger.warning(
            "TF-IDF fit failed (%s). Falling back to safe empty index (min_df=1, max_df=1.0).",
            e,
        )
        safe_vectorizer = TfidfVectorizer(
            # sklearn stubs used by Pyright can be overly strict here; at runtime a callable analyzer is valid.
            analyzer=cast(Any, make_mtg_analyzer((1, 2))),
            lowercase=False,
            min_df=1,
            max_df=1.0,
            sublinear_tf=True,
            norm=cast(Any, None),
        )
        vectorizer = safe_vectorizer
        matrix_raw = vectorizer.fit_transform(["__empty__"])

    matrix_l2 = normalize(matrix_raw, norm="l2", axis=1, copy=True)

    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info("TF-IDF index built: %d faces, %d features, %.2f ms", len(face_ids), len(vectorizer.vocabulary_), elapsed_ms)

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
        cache=TTLCache(maxsize=100, ttl=600),
    )


