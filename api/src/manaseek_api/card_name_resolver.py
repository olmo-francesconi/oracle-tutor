from typing import Mapping, Sequence, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel
from functools import lru_cache


class CardNameResolver:
    def __init__(self, card_entries: Sequence[Mapping[str, object]]):
        self.card_ids = [entry["id"] for entry in card_entries]
        self.card_names = [entry["name"] for entry in card_entries]
        self.card_ranks = [entry["edhrec_rank"] for entry in card_entries]
        self.card_rank_scores = np.array(
            [self._rank_score(rank, len(card_entries)) for rank in self.card_ranks],
            dtype=np.float32,
        )
        self.vectorizer = TfidfVectorizer(
            analyzer="char",
            ngram_range=(2, 4),
            lowercase=True,
        )
        self.name_matrix = self.vectorizer.fit_transform(self.card_names)

    @lru_cache(maxsize=2048)
    def _calculate_matches(self, text: str, rank_weight: float, rank_power: float):
        """Cache the search vector calculation and sorting"""
        q_vec = self.vectorizer.transform([text])
        sims = linear_kernel(q_vec, self.name_matrix).flatten()
        adjusted = self._apply_rank_weight(sims, rank_weight, rank_power)
        sorted_idx = np.argsort(adjusted)[::-1]
        return sorted_idx, sims, adjusted

    def top_matches(
        self,
        text: str,
        limit: int = 5,
        min_score: float = 0.2,
        rank_weight: float = 0.25,
        rank_power: float = 1.0,
    ) -> Sequence[dict]:
        """
        Return a list of dicts, each representing a card match with useful fields
        for API/JSON serialization.
        Each dict contains: name, id, rank, similarity, combined.
        """
        sorted_idx, sims, adjusted = self._calculate_matches(text, rank_weight, rank_power)

        results: list[dict] = []
        for idx in sorted_idx:
            similarity = float(sims[idx])
            if similarity < min_score:
                continue
            combined = float(adjusted[idx])
            results.append({
                "name": self.card_names[idx],
                "id": self.card_ids[idx],
                "rank": self.card_ranks[idx] if self.card_ranks[idx] else None,
                "similarity": similarity,
                "combined": combined,
            })
            if len(results) == limit:
                break
        return results

    def _rank_score(self, rank: int, cap: int) -> float:
        if not rank or not isinstance(rank, (int, float)) or rank <= 0:
            return 0.0
        clamped = max(1.0, min(float(rank), float(cap))) - 1.0
        return (cap - clamped) / cap

    def _apply_rank_weight(self, sims: np.ndarray, rank_weight: float, rank_power: float) -> np.ndarray:
        if not rank_weight:
            return sims
        return sims + (1 - sims) * rank_weight * pow(self.card_rank_scores, rank_power)
