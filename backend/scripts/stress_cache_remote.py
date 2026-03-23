#!/usr/bin/env python3
"""
Send many API requests to a remote Oracle Tutor deployment to stress the in-memory
TF-IDF cache. Use this to see if cache usage increases memory on Railway.

Usage:
  python backend/scripts/stress_cache_remote.py
  # default BASE_URL is https://oracletutor.org/api
  # override and/or run more rounds:
  BASE_URL=https://oracletutor.org/api STRESS_ROUNDS=5 python backend/scripts/stress_cache_remote.py
  # or from backend/:
  uv run python scripts/stress_cache_remote.py

Then check your deployment's memory metrics before/during/after the run.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.parse
import urllib.request

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | dict[str, "JsonValue"] | list["JsonValue"]
QueryParams = dict[str, str]

BASE_URL = os.environ.get("BASE_URL", "https://oracletutor.org/api").rstrip("/")
# Number of requests per "round" (search + similar + search-oracle)
SEARCH_QUERIES = [
    "lightning", "bolt", "dragon", "angel", "counter", "tutor", "draw", "ramp",
    "removal", "burn", "token", "counter", "doubling", "etb", "sacrifice",
]
FILTER_COMBOS = [
    {"card_type": "Creature", "colors": "R"},
    {"card_type": "Creature", "colors": "W"},
    {"card_type": "Instant", "colors": "U"},
    {"card_type": "Sorcery", "colors": "B"},
    {"format": "commander"},
    {"format": "modern"},
    {"colors": "G", "card_type": "Creature"},
    {"cmc_min": "0", "cmc_max": "2"},
    {"cmc_min": "4", "cmc_max": "6"},
]
ORACLE_QUERIES = [
    "draw a card", "destroy target", "deal damage", "create token",
    "counter target", "gain life", "lose life", "sacrifice", "enters the battlefield",
    "whenever you cast", "flying", "trample", "haste", "deathtouch",
]


def get(path: str, params: QueryParams | None = None) -> JsonValue:
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; OracleTutorCacheStress/1.0)",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def main() -> None:
    num_rounds = int(os.environ.get("STRESS_ROUNDS", "3"))
    total = 0
    errors = 0

    print(f"Target: {BASE_URL}")
    print(f"Rounds: {num_rounds} (each round = search + similar-cards + search-oracle with varied params)")
    print("Watch your deployment memory before/during/after.\n")

    # Collect card IDs from search
    card_ids: list[str] = []
    for q in SEARCH_QUERIES[:5]:
        try:
            results = get("/search", {"q": q, "limit": "10"})
            if isinstance(results, list):
                for r in results:
                    if isinstance(r, dict) and "id" in r:
                        card_id = r["id"]
                        if isinstance(card_id, str):
                            card_ids.append(card_id)
        except Exception as e:
            errors += 1
            print(f"  [skip search {q!r}] {e}", file=sys.stderr)
        total += 1
    card_ids = list(dict.fromkeys(card_ids))  # dedup
    if not card_ids:
        print("No card IDs from /search; similar-cards will be skipped.", file=sys.stderr)
    else:
        print(f"Got {len(card_ids)} card IDs for similar-cards requests.\n")

    for round_num in range(num_rounds):
        print(f"Round {round_num + 1}/{num_rounds} ...")
        # Search (warms name search; not TF-IDF cache but hits the service)
        for q in SEARCH_QUERIES:
            try:
                get("/search", {"q": q, "limit": "5"})
                total += 1
            except Exception as e:
                errors += 1
                print(f"  search {q!r}: {e}", file=sys.stderr)

        # Similar-cards (each card_id + filter combo = cache key)
        for cid in card_ids[:25]:
            for combo in FILTER_COMBOS:
                try:
                    get(f"/similar-cards/{cid}", {"limit": "20", **combo})
                    total += 1
                except Exception as e:
                    errors += 1
            # Also no filters
            try:
                get(f"/similar-cards/{cid}", {"limit": "20"})
                total += 1
            except Exception as e:
                errors += 1

        # Search-oracle (query text + filters = cache key)
        for q in ORACLE_QUERIES:
            for combo in random.sample(FILTER_COMBOS, min(3, len(FILTER_COMBOS))):
                try:
                    get("/search-oracle", {"q": q, "limit": "20", **combo})
                    total += 1
                except Exception as e:
                    errors += 1
            try:
                get("/search-oracle", {"q": q, "limit": "20"})
                total += 1
            except Exception as e:
                errors += 1

        print(f"  total requests so far: {total} (errors: {errors})")
        time.sleep(0.5)  # slight pause between rounds

    print(f"\nDone. Total requests: {total}, errors: {errors}")
    print("Check your deployment memory in Railway dashboard.")


if __name__ == "__main__":
    main()
