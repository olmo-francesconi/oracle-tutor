"""
Qualitative comparison between TF-IDF and semantic search endpoints.
Run with: pytest api/tests/test_semantic_vs_tfidf.py -s
Requires a running API at http://127.0.0.1:8000 with both indexes loaded.
"""

from __future__ import annotations

import pytest
import requests

BASE_URL = "http://127.0.0.1:8000"
QUERIES = [
    "deals damage to any target",
    "draw cards when creatures die",
    "create treasure tokens",
]


def _is_api_available() -> bool:
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=2)
    except requests.RequestException:
        return False
    return response.status_code == 200


pytestmark = pytest.mark.skipif(not _is_api_available(), reason="Local API is not running")


def _fetch(path: str, **params):
    response = requests.get(f"{BASE_URL}{path}", params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def test_semantic_vs_tfidf() -> None:
    for query in QUERIES:
        tfidf_rows = _fetch("/search-oracle", q=query, limit=5)
        semantic_rows = _fetch("/semantic/search-oracle", q=query, limit=5)

        print(f"\nQuery: {query}")
        print("TF-IDF:")
        for row in tfidf_rows:
            print(f"  {row['card_name']} ({row['similarity']:.4f})")

        print("Semantic:")
        for row in semantic_rows:
            print(f"  {row['card_name']} ({row['similarity']:.4f})")
