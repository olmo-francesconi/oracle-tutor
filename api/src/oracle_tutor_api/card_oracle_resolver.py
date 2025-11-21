import re
from functools import lru_cache
from typing import Mapping, Sequence, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class CardOracleResolver:
    def __init__(self, card_entries: Sequence[Mapping[str, object]]):
        """
        Initialize the resolver with card entries containing oracle text.
        
        Args:
            card_entries: Sequence of card dictionaries
        """
        self.card_ids = [card["id"] for card in card_entries]
        self.card_names = [card["name"] for card in card_entries]
        self.oracle_texts = [self._clean_oracle_text(card["oracle_text"] or "", card["name"]) for card in card_entries]
        self.card_ranks = [card["edhrec_rank"] for card in card_entries]
        self.card_rank_scores = np.array(
            [self._rank_score(rank, len(card_entries)) for rank in self.card_ranks],
            dtype=np.float32,
        )
        
        # Build TF-IDF vectorizer for oracle text
        # Using word-level n-grams for better semantic matching
        self.vectorizer = TfidfVectorizer(
            analyzer="word",
            ngram_range=(1, 2),  # Unigrams and bigrams
            lowercase=True,
            max_features=10000,  # Limit features for performance
            stop_words="english",  # Remove common English stop words
        )
        
        # Fit and transform all oracle texts
        self.oracle_matrix = self.vectorizer.fit_transform(self.oracle_texts)
        

    @lru_cache(maxsize=1024)
    def _calculate_similarities(
        self, 
        card_id: str, 
        rank_weight: float = 0.15, 
        rank_power: float = 1.0
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Calculate and sort similarities for a given card. 
        Cached to avoid re-computing matrices for the same card.
        Returns (sorted_indices, adjusted_scores)
        """
        # Find the index of the card
        try:
            card_idx = self.card_ids.index(card_id)
        except ValueError:
            return None, None
        
        # Get the oracle text vector for this card
        query_vector = self.oracle_matrix[card_idx:card_idx+1]
        
        # Calculate cosine similarity with all cards
        similarities = cosine_similarity(query_vector, self.oracle_matrix).flatten()
        
        # Apply rank weighting
        adjusted = self._apply_rank_weight(similarities, rank_weight, rank_power)
        
        # Sort by adjusted score (descending)
        sorted_idx = np.argsort(adjusted)[::-1]
        
        return sorted_idx, adjusted

    def find_similar_cards(
        self,
        card_id: str,
        limit: int = 20,
        offset: int = 0,
        min_score: float = 0.1,
        rank_weight: float = 0.15,
        rank_power: float = 1.0,
        exclude_self: bool = True,
    ) -> Sequence[dict]:
        """
        Find cards similar to the given card ID based on oracle text similarity.
        
        Args:
            card_id: The ID of the card to find similar cards for
            limit: Maximum number of results to return
            offset: Number of results to skip (for pagination)
            min_score: Minimum similarity score to include (0-1)
            rank_weight: Weight for EDHREC rank adjustment (0-1)
            rank_power: Power factor for rank adjustment
            exclude_self: Whether to exclude the query card from results
        
        Returns:
            List of dicts with: id, name, similarity, rank, combined
        """
        # CALL THE CACHED METHOD
        sorted_idx, adjusted = self._calculate_similarities(card_id, rank_weight, rank_power)
        
        if sorted_idx is None:
            return []
            
        # Find the index of the card (needed for exclude_self check)
        try:
            card_idx = self.card_ids.index(card_id)
        except ValueError:
            return [] # Should be caught by _calculate_similarities but safe to keep

        results: list[dict] = []
        skipped = 0
        
        # Iterate through the pre-calculated sorted list
        for idx in sorted_idx:
            # Skip the card itself if requested
            if exclude_self and idx == card_idx:
                continue

            
            combined = float(adjusted[idx])
            
            if combined < min_score:
                 continue

            # Skip results based on offset
            if skipped < offset:
                skipped += 1
                continue
            
            results.append({
                "id": self.card_ids[idx],
                "name": self.card_names[idx],
                "rank": self.card_ranks[idx] if self.card_ranks[idx] else None,
                "similarity": combined, # Simplified: use combined as primary score
                "combined": combined,
            })
            
            if len(results) == limit:
                break
        
        return results

    def _clean_oracle_text(self, text: str, card_name: str = "") -> str:
        """
        Clean oracle text by removing parenthetical text and normalizing special characters.
        
        Args:
            text: The original oracle text
            card_name: The name of the card (used to normalize self-references)
            
        Returns:
            Cleaned oracle text with parentheses removed and special characters normalized
        """
        # Remove all text between parentheses (including nested parentheses)
        cleaned = text
        while True:
            new_cleaned = re.sub(r'\([^()]*\)', '', cleaned)
            if new_cleaned == cleaned:
                break
            cleaned = new_cleaned
        
        # Normalize card name references (replace card name with CARD_NAME placeholder)
        if card_name:
            # Escape special regex characters in the card name
            escaped_name = re.escape(card_name)
            # Replace card name with CARD_NAME (case-insensitive, whole word matching)
            # Use word boundaries to ensure we match whole words only
            cleaned = re.sub(r'\b' + escaped_name + r'\b', ' CARD_NAME ', cleaned, flags=re.IGNORECASE)
        
        # Normalize special characters and symbols
        # Tap and untap symbols
        cleaned = re.sub(r'\{T\}', ' TAP_ABILITY ', cleaned)
        cleaned = re.sub(r'\{Q\}', ' UNTAP_ABILITY ', cleaned)
        
        # Basic mana symbols
        cleaned = re.sub(r'\{W\}', ' WHITE_MANA ', cleaned)
        cleaned = re.sub(r'\{U\}', ' BLUE_MANA ', cleaned)
        cleaned = re.sub(r'\{B\}', ' BLACK_MANA ', cleaned)
        cleaned = re.sub(r'\{R\}', ' RED_MANA ', cleaned)
        cleaned = re.sub(r'\{G\}', ' GREEN_MANA ', cleaned)
        cleaned = re.sub(r'\{C\}', ' COLORLESS_MANA ', cleaned)
        
        # Generic mana (numbers)
        cleaned = re.sub(r'\{(\d+)\}', r' GENERIC_MANA_\1 ', cleaned)
        
        # Variable mana
        cleaned = re.sub(r'\{X\}', ' VARIABLE_MANA_X ', cleaned)
        cleaned = re.sub(r'\{Y\}', ' VARIABLE_MANA_Y ', cleaned)
        cleaned = re.sub(r'\{Z\}', ' VARIABLE_MANA_Z ', cleaned)
        
        # Hybrid mana (e.g., {W/U}, {2/W})
        cleaned = re.sub(r'\{([WUBRGC])\/([WUBRGC])\}', r' HYBRID_MANA_\1\2 ', cleaned)
        cleaned = re.sub(r'\{(\d+)\/([WUBRGC])\}', r' HYBRID_MANA_\1\2 ', cleaned)
        
        # Phyrexian mana (e.g., {W/P}, {R/P})
        cleaned = re.sub(r'\{([WUBRGC])\/P\}', r' PHYREXIAN_MANA_\1 ', cleaned)
        
        # Snow mana
        cleaned = re.sub(r'\{S\}', ' SNOW_MANA ', cleaned)
        
        # Energy
        cleaned = re.sub(r'\{E\}', ' ENERGY ', cleaned)
        
        # Half mana (very rare, from Unstable)
        cleaned = re.sub(r'\{H([WUBRGC])\}', r' HALF_MANA_\1 ', cleaned)
        
        # Chaos symbol (rare, Planechase)
        cleaned = re.sub(r'\{CHAOS\}', ' CHAOS_SYMBOL ', cleaned)
        
        # Clean up extra whitespace (multiple spaces/newlines)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = cleaned.strip()
        
        return cleaned

    def _rank_score(self, rank: int, cap: int) -> float:
        """Convert EDHREC rank to a normalized score (0-1)."""
        if not rank or not isinstance(rank, (int, float)) or rank <= 0:
            return 0.0
        clamped = max(1.0, min(float(rank), float(cap))) - 1.0
        return (cap - clamped) / cap

    def _apply_rank_weight(
        self, sims: np.ndarray, rank_weight: float, rank_power: float
    ) -> np.ndarray:
        """Apply rank-based adjustment to similarity scores."""
        if not rank_weight:
            return sims
        return sims + (1 - sims) * rank_weight * pow(self.card_rank_scores, rank_power)

