import numpy as np
import pytest

from app.search import query_abilities


def ids(hits):
    return [(c["oracle_id"], f["face_ix"]) for c, f, _, _ in hits]


def scores(hits):
    return {(c["oracle_id"], f["face_ix"]): s for c, f, s, _ in hits}


def everything(index):
    return np.ones(len(index.faces), dtype=bool)


def test_tap_query_matches_both_creature_and_land_corpus_text(index):
    # The corpus renders {T} as "tap this creature" / "tap this land"; the query must reach both exactly.
    hits = scores(index.search_text(query_abilities("{T}: Add {G}."), 3, everything(index)))
    assert hits[("elf", 0)] == pytest.approx(1.0)
    assert hits[("forest", 0)] == pytest.approx(1.0)


def test_query_goes_through_corpus_segmentation():
    assert [d for d, _ in query_abilities("flying, vigilance // draw a card")] == ["flying", "vigilance", "draw a card"]
    assert len(query_abilities("draw a card")[0][1]) == 1  # no {T}: one variant
    assert query_abilities("(reminder only)") == []


def test_multi_ability_query_requires_every_ability(index):
    hits = index.search_text(query_abilities("flying // when this creature enters, draw a card"), 10, everything(index))
    assert ids(hits)[0] == ("bird", 0)
    s = scores(hits)
    assert s[("bird", 0)] > s[("drake", 0)] > s[("bolt", 0)]


def test_card_mode_is_bidirectional_and_excludes_the_seed(index):
    hits = index.similar_to_face("bird", 0, 20, everything(index))
    assert ("bird", 0) not in ids(hits)
    s = [score for *_, score, _ in hits]
    assert s == sorted(s, reverse=True)
    # Sky Drake matches the seed's flying but explains only half the seed: < 1.
    assert scores(hits)[("drake", 0)] < 0.9


def test_selecting_every_ability_is_identical_to_no_tuning(index):
    alive = everything(index)
    assert index.similar_to_face("bird", 0, 20, alive, include=[0, 1]) == index.similar_to_face("bird", 0, 20, alive)


def test_including_a_subset_switches_to_forward(index):
    hits = scores(index.similar_to_face("bird", 0, 20, everything(index), include=[0]))
    assert hits[("drake", 0)] == pytest.approx(1.0)


def test_excluding_an_ability_drops_cards_that_print_it(index):
    hits = ids(index.similar_to_face("bird", 0, 20, everything(index), exclude=[0]))
    assert ("drake", 0) not in hits and ("dfc", 0) not in hits
    assert ("seer", 0) in hits


def test_exclude_wins_over_include(index):
    assert index.similar_to_face("bird", 0, 20, everything(index), include=[0], exclude=[0]) == []
    hits = ids(index.similar_to_face("bird", 0, 20, everything(index), include=[0, 1], exclude=[0]))
    assert ("drake", 0) not in hits


def test_unknown_face_returns_nothing(index):
    assert index.similar_to_face("nope", 0, 20, everything(index)) == []
    assert index.similar_to_face("bird", 5, 20, everything(index)) == []


def test_idf_weights_common_text_lower(index):
    flying = index.inst_idf[index.starts[index.face_pos[("drake", 0)]]]
    bolt = index.inst_idf[index.starts[index.face_pos[("bolt", 0)]]]
    assert flying < bolt


def test_matched_ability_prefers_relevant_then_distinctive(index):
    hit = next(h for h in index.search_text(query_abilities("draw a card"), 10, everything(index)) if h[0]["oracle_id"] == "bird")
    assert hit[3] == "When this creature enters, draw a card."
    # Vanilla faces have only the placeholder ability: nothing to show.
    bear = next(h for h in index.search_text(query_abilities("draw a card"), 20, everything(index)) if h[0]["oracle_id"] == "bear")
    assert bear[3] is None


def masked(index, **filters):
    return {index.faces[i][0]["oracle_id"] + f"/{index.faces[i][1]['face_ix']}" for i in np.flatnonzero(index.mask(**filters))}


def test_filters(index):
    assert masked(index, card_type=["land"]) == {"forest/0"}
    assert masked(index, card_type=["instant", "enchantment"]) == {"bolt/0", "seer/0"}
    assert masked(index, cmc_min=2, cmc_max=2) == {"seer/0", "bear/0"}
    assert masked(index, rarity=["rare", "uncommon"]) == {"seer/0", "bird/0"}
    assert masked(index, formats=["vintage"]) == {"bolt/0"}  # restricted counts as eligible
    assert masked(index, colors="G") == {"elf/0", "bear/0"}
    assert masked(index, colors="G", match_mode="at_most") == {"elf/0", "bear/0", "forest/0"}
    assert masked(index, colors="UB", match_mode="at_most") == {"drake/0", "bird/0", "seer/0", "forest/0"}
    assert masked(index, colors="U", match_mode="exact", color_feature="colors") == {"drake/0", "bird/0"}
    assert masked(index, colors="xyz") == masked(index)  # invalid colour chars skip the filter


def test_filters_apply_before_truncation(index):
    hits = index.search_text(query_abilities("flying"), 1, index.mask(card_type=["land"]))
    assert ids(hits) == [("forest", 0)]


def test_name_search_ranks_exact_then_prefix_then_substring(index):
    def names(q):
        return [f["name"] for _, f in index.search_names(q, 10, 0)]

    assert names("bird") == ["Night Bird"]
    assert names("bolt") == ["Bolt"]
    # Prefix matches first, then substring; edhrec rank (nulls last), card name, face_ix break ties.
    assert names("g") == ["Grave Seer", "Green Land", "Night Bird", "Wing Squire", "Trample Knight"]
    assert names("d") == ["Llanowar Dork", "Night Bird", "Sky Drake", "Green Land"]
    assert names("trample") == ["Trample Knight"]
    assert names("  ") == []


def test_oracle_samples(index):
    index.keyword_lists.append([" Flying", "flying"])
    texts, terms = index.oracle_samples(3)
    assert len(texts) == 3 and all(t.strip() for t in texts)
    assert terms == ["Flying"]
