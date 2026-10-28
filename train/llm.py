"""LLM-written search queries per ability text, cached by `text_hash` so each text is generated once.

The cache is `training/llm_queries.jsonl.gz` in the bucket (train/llm_queries.jsonl.gz without one), one row per
distinct ability text: {"hash", "text", "queries", "llm"}. train/dataset.py generates only the hashes it lacks, on
Modal with vLLM; new cards add a few hundred texts per set, so a refreshed dataset costs minutes, not a full pass.

Prompting, model and limits are v2's. v2 prompted only "gap" texts (fewer than two template-query rule hits) and capped
a run at SEMANTIC_LLM_MAX_FACES to bound GPU spend per run. The template rules are gone (they were type-blind and
harmful, see CLAUDE.md), and the cache bounds spend instead, so every distinct ability text is a candidate: one full
pass, then only new text. `--llm-limit` caps a run.
"""

import gzip
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path

from app import snapshot
from app.text import ability_text_hash

CACHE_KEY = "training/llm_queries.jsonl.gz"
LOCAL_CACHE = Path("train/llm_queries.jsonl.gz")
LLM_MODEL = "Qwen/Qwen2.5-14B-Instruct-AWQ"
QUERIES_PER_ABILITY = 5
TEMPERATURE = 0.8
MAX_TOKENS = 600
# 8 words of ordinary English; anything longer is a generation artifact.
_MAX_QUERY_CHARS = 80
_SYSTEM_PROMPT = f"""\
You are a search query generator for a Magic: The Gathering card database.
When given card oracle text, output exactly {QUERIES_PER_ABILITY} short search queries that a player might type to find \
cards with this effect.

Rules:
- Each query must be 2-8 words, all lowercase
- Use Magic: The Gathering terminology where appropriate (e.g. "draw a card", "counter a spell", "enters the \
battlefield", "tap for mana")
- Describe what the card DOES — its mechanic or effect — not its name
- Output one query per line, nothing else: no numbering, no bullets, no explanation
- Focus on the most distinctive or searchable thing the card does"""
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_LIST_PREFIX = re.compile(r"^[\s\-\*•\d\.\)]+")


def conversation(printed_text: str) -> list[dict]:
    # The printed wording is what the LLM understands; the pair's positive is the normalized text that is embedded.
    return [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": f"Oracle text:\n{printed_text}"}]


def parse_queries(raw: str, max_queries: int = QUERIES_PER_ABILITY) -> list[str]:
    out: list[str] = []
    for line in _THINK_BLOCK.sub("", raw).splitlines():
        query = _LIST_PREFIX.sub("", line).strip().rstrip(".,;:").lower()
        # Word count alone does not bound length: a repetition loop ("...ationationation...") has no spaces, and 329
        # such 4,000-character "queries" once reached a v2 dataset.
        if 2 <= len(query.split()) <= 8 and len(query) <= _MAX_QUERY_CHARS and query not in out:
            out.append(query)
        if len(out) == max_queries:
            break
    return out


def load_cache() -> dict[str, dict]:
    body = snapshot.get(CACHE_KEY) if snapshot.enabled() else (LOCAL_CACHE.read_bytes() if LOCAL_CACHE.exists() else None)
    rows = gzip.decompress(body).decode().splitlines() if body else []
    return {r["hash"]: r for r in map(json.loads, rows)}


def save_cache(cache: Mapping[str, dict]) -> None:
    body = gzip.compress("".join(json.dumps(cache[h], ensure_ascii=False) + "\n" for h in sorted(cache)).encode(),
                         mtime=0)
    if snapshot.enabled():
        snapshot.put(CACHE_KEY, body, "application/gzip")
    else:
        LOCAL_CACHE.write_bytes(body)


def fill_cache(cache: dict[str, dict], printed: Mapping[str, str], normalized: Mapping[str, str],
               limit: int | None) -> int:
    """Generate queries for up to `limit` (None = all) texts missing from `cache`, in place. Returns how many.

    A text whose output parses to no query is cached with `queries: []`, so it is not re-generated every run."""
    todo = [h for h in sorted(printed) if h not in cache][:limit]
    print(f"llm cache: {len(cache):,} texts cached · {len(todo):,} to generate ({LLM_MODEL})", flush=True)
    if not todo:
        return 0
    import modal

    from train import remote

    with modal.enable_output(), remote.app.run(environment_name=remote.ENVIRONMENT):
        raw = remote.generate.remote([conversation(printed[h]) for h in todo], LLM_MODEL, TEMPERATURE, MAX_TOKENS)
    for h, text in zip(todo, raw, strict=True):
        cache[h] = {"hash": h, "text": normalized[h], "queries": parse_queries(text), "llm": LLM_MODEL}
    empty = sum(not cache[h]["queries"] for h in todo)
    print(f"llm generated {len(todo):,}: {len(todo) - empty:,} with queries · {empty:,} empty (cached as empty)",
          flush=True)
    return len(todo)


def seed_from_v2(direct_text_pairs: Iterable[list[str]], tag_anchors: set[str], llm: str) -> dict[str, dict]:
    """Recover LLM rows from a v2 bundle's training/training-dataset.json `direct_text_pairs`.

    v2 stored LLM pairs untagged among the tag-description pairs. LLM pairs are the 2-column rows whose anchor is no
    tag anchor: not a triplet's anchor (tags with a negative pool) and not in `tag_anchors` (current tags). Tags
    renamed since leave a few stale anchors behind, so a text keeps at most QUERIES_PER_ABILITY queries that also pass
    `parse_queries`'s shape rules."""
    rows = list(direct_text_pairs)
    tagged = tag_anchors | {r[0] for r in rows if len(r) == 3}
    queries: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if len(row) == 2 and row[0] not in tagged:
            queries[row[1]].append(row[0])
    cache = {}
    for text, qs in queries.items():
        kept = parse_queries("\n".join(qs))
        if kept:
            h = ability_text_hash(text)
            cache[h] = {"hash": h, "text": text, "queries": kept, "llm": llm}
    return cache


def pairs(cache: Mapping[str, dict], texts: Iterable[str]) -> list[tuple[str, str]]:
    """(query, ability text) for every cached text in `texts`."""
    return [(q, t) for t in dict.fromkeys(texts) for q in cache.get(ability_text_hash(t), {}).get("queries", ())]
