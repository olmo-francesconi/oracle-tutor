import random
import time

from app.text import ability_text_hash
from train import llm
from train.dataset import build_examples
from train.train import model_id_for, subsample


def test_queries_are_parsed_bounded_and_deduplicated():
    raw = "<think>hmm</think>\n1. Draw A Card.\n- draw a card\n• card\nx" + "ation" * 30 + " y\nloot then draw\n"
    assert llm.parse_queries(raw) == ["draw a card", "loot then draw"]
    assert len(llm.parse_queries("\n".join(f"query number {i}" for i in range(9)))) == llm.QUERIES_PER_ABILITY


def test_v2_llm_rows_are_told_apart_from_tag_rows():
    rows = [
        ["tap for green mana", "tap this creature: Add one green mana."],
        ["mana elf creature", "tap this creature: Add one green mana."],
        ["mana dork", "tap this creature: Add one green mana."],  # tag anchor without a negative pool
        ["ramp", "tap this creature: Add one green mana.", "Flying."],  # triplet: its anchor is a tag
        ["ramp", "Search your library for a basic land card."],
        ["fetch a basic land", "Search your library for a basic land card."],
    ]
    cache = llm.seed_from_v2(rows, {"mana dork"}, "m")
    dork = ability_text_hash("tap this creature: Add one green mana.")
    fetch = ability_text_hash("Search your library for a basic land card.")
    assert cache[dork]["queries"] == ["tap for green mana", "mana elf creature"]
    assert cache[fetch] == {"hash": fetch, "text": "Search your library for a basic land card.",
                            "queries": ["fetch a basic land"], "llm": "m"}


def test_cache_round_trips_and_only_missing_texts_are_generated(tmp_path, monkeypatch):
    monkeypatch.delenv("BUCKET", raising=False)
    monkeypatch.setattr(llm, "LOCAL_CACHE", tmp_path / "c.jsonl.gz")
    h = ability_text_hash("Flying.")
    cache = {h: {"hash": h, "text": "Flying.", "queries": ["flying creature"], "llm": "m"}}
    llm.save_cache(cache)
    assert llm.load_cache() == cache
    # Nothing missing: no Modal call (fill_cache would import modal and fail without auth in CI).
    assert llm.fill_cache(cache, {h: "Flying"}, {h: "Flying."}, None) == 0
    assert llm.fill_cache(cache, {h: "Flying", "other": "Trample"}, {}, 0) == 0
    assert llm.pairs(cache, ["Flying.", "Flying.", "Trample."]) == [("flying creature", "Flying.")]


def test_augmentations_can_be_switched_off():
    texts = {("a", 0, 0): "x", ("b", 0, 0): "y", ("c", 0, 0): "z"}
    tags = {"t": [("a", 0, 0), ("b", 0, 0)], "u": [("a", 0, 0), ("b", 0, 0), ("c", 0, 0)]}
    pairs, triplets = build_examples(texts, tags, {}, random.Random(0), augment=())
    assert sorted(pairs) == [("x", "x"), ("y", "y"), ("z", "z")] and triplets == []
    pairs, triplets = build_examples(texts, tags, {}, random.Random(0), augment={"tag_pairs"})
    assert len(pairs) > 3 and triplets == []
    pairs, triplets = build_examples(texts, tags, {}, random.Random(0), augment={"tag_descriptions"})
    assert {p[0] for p in pairs[3:]} == {"t", "u"}  # anchors; no co-tag overlaps enough for a negative pool


def test_smoke_limit_keeps_the_pair_triplet_mix():
    data = {"pairs": list(range(900)), "triplets": list(range(100)), "stats": {}}
    small = subsample(data, 100, random.Random(0))
    assert (len(small["pairs"]), len(small["triplets"])) == (90, 10)
    assert subsample(data, 5000, random.Random(0)) is data


def test_model_ids_are_readable_and_timestamped():
    now = time.strptime("2026-10-28 17:05", "%Y-%m-%d %H:%M")
    assert model_id_for("sentence-transformers/all-MiniLM-L6-v2", None, now) == "all-minilm-l6-v2-20261028-1705"
    assert model_id_for("x", "tags-llm", now) == "tags-llm-20261028-1705"
