from __future__ import annotations

import logging

logger = logging.getLogger("ot_backend.semantic.uniqueness")

UNIQUENESS_THRESHOLD = 0.40
UNIQUENESS_POWER = 2.0
UNIQUENESS_BATCH_SIZE = 500


def compute_and_store_uniqueness_scores(session) -> None:
    logger.warning("Uniqueness scoring is disabled: card_face_semantic_embeddings table has been dropped.")
