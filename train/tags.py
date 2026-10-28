"""Download Scryfall's oracle-tags bulk file to train/tags.jsonl.gz.

Run from repo root: uv run --project train python -m train.tags

v2 scraped Tagger's GraphQL once per card (~33k CSRF-session calls, ~9h). Scryfall now publishes every oracle tag
with its member oracle_ids as one bulk file (~6 MB), so the snapshot is a single download.
"""

import gzip
import hashlib
import json
import urllib.request
from pathlib import Path

BULK_URL = "https://api.scryfall.com/bulk-data/oracle-tags"
# Scryfall rejects requests without an explicit User-Agent and Accept header (HTTP 400/403).
HEADERS = {"User-Agent": "OracleTutor/3.0.0 (+https://oracletutor.org)", "Accept": "application/json"}
TAGS_PATH = Path("train/tags.jsonl.gz")

# Share of tags reserved for evaluation and excluded from training.
HOLDOUT_PERCENT = 15
# Same salt and key (the tag's display name, "mana dork") as v2, so models trained there are scored on tags they
# never saw.
_HOLDOUT_SALT = "ot-tag-holdout-v1"


def is_held_out_tag(name: str, holdout_percent: int = HOLDOUT_PERCENT) -> bool:
    """Whether a tag belongs to the eval split.

    Hash-based rather than a stored sample: the same tag always lands on the same side, no state to keep in sync
    between the trainer and the evaluator, and adding tags never reshuffles the existing split.
    """
    digest = hashlib.sha256(f"{_HOLDOUT_SALT}:{name}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % 100 < holdout_percent


def load_tags(path: Path = TAGS_PATH) -> dict[str, tuple[str | None, list[str]]]:
    """tag name -> (description, oracle_ids)."""
    with gzip.open(path, "rt") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return {r["label"]: (r["description"], [t["oracle_id"] for t in r["taggings"]]) for r in rows}


def main() -> None:
    meta = json.load(urllib.request.urlopen(urllib.request.Request(BULK_URL, headers=HEADERS)))
    # Served as application/gzip without Content-Encoding, so the bytes are the .gz file as-is.
    body = urllib.request.urlopen(urllib.request.Request(meta["jsonl_download_uri"], headers=HEADERS)).read()
    TAGS_PATH.write_bytes(body)
    print(f"wrote {TAGS_PATH}: {len(load_tags())} tags, updated_at {meta['updated_at']}")


if __name__ == "__main__":
    main()
