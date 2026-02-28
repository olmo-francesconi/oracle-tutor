"""
Standalone TF-IDF index builder for subprocess-based rebuilds.

Run as: python -m oracle_tutor_api.api.tfidf_build_standalone <output_path>

Reads DATABASE_URL from the environment, builds the index, and writes a pickle
to output_path. The API process can then load this file and swap the index,
so the large build allocations are made in this process and fully reclaimed
when it exits (avoiding RSS step-up from glibc fragmentation in the API process).

Must be run with PYTHONPATH including the api src (e.g. from api/: uv run python -m oracle_tutor_api.api.tfidf_build_standalone /tmp/tfidf.pkl).
"""

from __future__ import annotations

import logging
import pickle
import sys

from ..core.database import SessionLocal
from .tfidf_index import build_tfidf_index

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    if len(sys.argv) != 2:
        logger.error("Usage: python -m oracle_tutor_api.api.tfidf_build_standalone <output_path>")
        return 1
    output_path = sys.argv[1]

    db = SessionLocal()
    try:
        index = build_tfidf_index(db)
        with open(output_path, "wb") as f:
            pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info("Wrote TF-IDF index to %s", output_path)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
