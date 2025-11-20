import re
from typing import Mapping, Sequence

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class CardOracleResolver:
    def __init__(self, card_entries: Sequence[Mapping[str, object]]):
        """
        Initialize the resolver with card entries containing oracle text.
        
        Args:
            card_entries: Sequence of card dictionaries with at least 'id' and 'oracle_text' fields.
        """
        self.card_ids = []
        self.card_names = []
        self.oracle_texts = []
        self.card_ranks = []
        
        # Filter out cards without oracle text
        for entry in card_entries:
            card_id = entry.get("id")
            oracle_text = entry.get("oracle_text") or ""
            card_name = entry.get("name", "")
            
            # Skip cards without ID or with empty oracle text
            if not card_id:
                continue
            
            # Clean the oracle text before storing
            cleaned_text = self._clean_oracle_text(oracle_text, card_name)
            
            self.card_ids.append(card_id)
            self.card_names.append(card_name)
            self.oracle_texts.append(cleaned_text)
            self.card_ranks.append(entry.get("edhrec_rank"))
        
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
        
        # Pre-compute rank scores for all cards
        self.card_rank_scores = np.array(
            [self._rank_score(rank, len(self.card_ids)) for rank in self.card_ranks],
            dtype=np.float32,
        )

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
            min_score: Minimum similarity score (0-1) to include
            rank_weight: Weight for EDHREC rank adjustment (0-1)
            rank_power: Power factor for rank adjustment
            exclude_self: Whether to exclude the query card from results
        
        Returns:
            List of dicts with: id, name, similarity, rank, combined
        """
        # Find the index of the card
        try:
            card_idx = self.card_ids.index(card_id)
        except ValueError:
            return []
        
        # Get the oracle text vector for this card
        query_vector = self.oracle_matrix[card_idx:card_idx+1]
        
        # Calculate cosine similarity with all cards
        similarities = cosine_similarity(query_vector, self.oracle_matrix).flatten()
        
        # Apply rank weighting
        adjusted = self._apply_rank_weight(similarities, rank_weight, rank_power)
        
        # Sort by adjusted score (descending)
        sorted_idx = np.argsort(adjusted)[::-1]
        
        results: list[dict] = []
        skipped = 0
        for idx in sorted_idx:
            # Skip the card itself if requested
            if exclude_self and idx == card_idx:
                continue
            
            similarity = float(similarities[idx])
            if similarity < min_score:
                continue
            
            # Skip results based on offset
            if skipped < offset:
                skipped += 1
                continue
            
            combined = float(adjusted[idx])
            results.append({
                "id": self.card_ids[idx],
                "name": self.card_names[idx],
                "rank": self.card_ranks[idx] if self.card_ranks[idx] else None,
                "similarity": similarity,
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
        if not text:
            return text
        
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

