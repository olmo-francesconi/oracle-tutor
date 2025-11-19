from typing import Mapping, Sequence, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel


class CardNameResolver:
    def __init__(self, card_entries: Sequence[Mapping[str, object]]):
        self.card_names = [entry["name"] for entry in card_entries]
        self.rank_scores = np.array(
            [self._rank_score(entry.get("edhrec_rank")) for entry in card_entries],
            dtype=np.float32,
        )
        self.vectorizer = TfidfVectorizer(
            analyzer="char",
            ngram_range=(2, 4),
            lowercase=True,
        )
        self.name_matrix = self.vectorizer.fit_transform(self.card_names)

    def best_match(
        self,
        text: str,
        min_score: float = 0.35,
        rank_weight: float = 0.2,
    ) -> Tuple[str, float]:
        matches = self.top_matches(
            text,
            limit=1,
            min_score=min_score,
            rank_weight=rank_weight,
        )
        if not matches:
            return "", 0.0
        name, similarity, _ = matches[0]
        return name, similarity

    def top_matches(
        self,
        text: str,
        limit: int = 5,
        min_score: float = 0.2,
        rank_weight: float = 0.2,
        rank_power: float = 1.0,
    ) -> Sequence[Tuple[str, float, float]]:
        q_vec = self.vectorizer.transform([text])
        sims = linear_kernel(q_vec, self.name_matrix).flatten()
        adjusted = self._apply_rank_weight(sims, rank_weight, rank_power)
        if limit >= len(self.card_names):
            candidate_idx = np.argsort(adjusted)[::-1]
        else:
            idx_part = np.argpartition(adjusted, -limit)[-limit:]
            candidate_idx = idx_part[np.argsort(adjusted[idx_part])[::-1]]

        results: list[Tuple[str, float, float]] = []
        for idx in candidate_idx:
            similarity = float(sims[idx])
            if similarity < min_score:
                continue
            combined = float(adjusted[idx])
            results.append((self.card_names[idx], similarity, combined))
        return results

    @staticmethod
    def _rank_score(rank) -> float:
        if not rank or not isinstance(rank, (int, float)) or rank <= 0:
            return 0.0
        cap = 10000
        clamped = max(1.0, min(float(rank), float(cap))) - 1.0
        return (cap - clamped) / cap

    def _apply_rank_weight(self, sims: np.ndarray, rank_weight: float, rank_power: float = 1.0) -> np.ndarray:
        if not rank_weight:
            return sims
        return (1 - rank_weight) * sims + rank_weight * pow(self.rank_scores, rank_power)
