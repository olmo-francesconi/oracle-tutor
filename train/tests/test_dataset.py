import random

from train.dataset import _HARD_NEGATIVE_POOL_CAP, MIN_MEMBERS, attribute_tags, build_examples, hard_negative_pools
from train.tags import HOLDOUT_PERCENT, is_held_out_tag

N = MIN_MEMBERS + 10


def _corpus(dorks: int = N) -> dict:
    # Background makes "flying" common, as it is in reality; otherwise lift would rightly call it distinctive.
    corpus = {}
    for i in range(40):
        corpus[(f"flier{i}", 0, 0)] = "flying."
        corpus[(f"other{i}", 0, 0)] = "destroy target permanent."
    for i in range(dorks):
        corpus[(f"dork{i}", 0, 0)] = "tap this creature: add one green mana."
        corpus[(f"dork{i}", 0, 1)] = "flying."
    return corpus


def _dorks(n: int = N) -> list:
    return [(f"dork{i}", 0) for i in range(n)]


def test_a_tag_attaches_to_the_ability_that_carries_it_not_the_whole_face():
    picks = attribute_tags(_corpus(), {"mana-dork": _dorks()}, {})["mana-dork"]
    assert picks and all(ability_ix == 0 for _, _, ability_ix in picks)


def test_an_unseparated_face_is_dropped_rather_than_guessed():
    assert attribute_tags(_corpus(), {"mana-dork": _dorks()}, {}, min_margin=99.0)["mana-dork"] == []


def test_an_unscoreable_ability_never_wins_on_a_fabricated_margin():
    corpus = _corpus()
    for oracle_id, face_ix in _dorks():
        corpus[(oracle_id, face_ix, 2)] = "—"
    picks = attribute_tags(corpus, {"mana-dork": _dorks()}, {})["mana-dork"]
    assert picks and all(ability_ix == 0 for _, _, ability_ix in picks)


def test_a_tag_no_ability_can_justify_is_dropped_whole():
    corpus, members = _corpus(0), []
    for i in range(N):
        corpus[(f"allit{i}", 0, 0)] = f"when this creature enters, draw {i} cards."
        corpus[(f"allit{i}", 0, 1)] = f"whenever this creature attacks, it gets plus {i} strength."
        members.append((f"allit{i}", 0))
    corpus[("solo", 0, 0)] = "target player discards two cards."
    members.append(("solo", 0))
    assert attribute_tags(corpus, {"alliteration": members}, {})["alliteration"] == []


def test_a_small_tag_keeps_only_its_single_ability_members():
    corpus, members = _corpus(10), _dorks(10)
    for i in range(4):
        corpus[(f"solo{i}", 0, 0)] = f"destroy target creature. {i}"
        members.append((f"solo{i}", 0))
    assert sorted(attribute_tags(corpus, {"rare": members}, {})["rare"]) == [(f"solo{i}", 0, 0) for i in range(4)]


def test_negatives_come_from_specifically_related_tags_only():
    members = [f"m{i}" for i in range(10)]
    pools = hard_negative_pools({
        "t": members,
        "activated-ability": [*members, *[f"g{i}" for i in range(500)]],  # overlaps 10, huge
        "adds-multiple-mana": [*members[:5], "s1", "s2"],  # overlaps 5, tight
        "coincidence": ["m0", "c1"],  # one shared member is noise
    })
    assert pools["t"][0] in {"s1", "s2"}
    assert not set(pools["t"]) & set(members)
    assert "c1" not in pools["t"]


def test_pools_are_bounded():
    pools = hard_negative_pools({"t": ["x"] * 3, "huge": ["x", *range(5000)]})
    assert len(pools["t"]) <= _HARD_NEGATIVE_POOL_CAP


def test_a_negative_never_equals_any_of_the_tags_positives():
    # n0 has the same text as positive a1: v2 would emit it as a negative for anchor/a0.
    texts = {("a0", 0, 0): "x", ("a1", 0, 0): "y", ("a2", 0, 0): "z", ("n0", 0, 0): "y", ("n1", 0, 0): "w"}
    tags = {"t": [("a0", 0, 0), ("a1", 0, 0), ("a2", 0, 0)], "u": [("a0", 0, 0), ("a1", 0, 0), ("a2", 0, 0),
                                                                    ("n0", 0, 0), ("n1", 0, 0)]}
    _, triplets = build_examples(texts, tags, {}, random.Random(0))
    assert {neg for anchor, _, neg in triplets if anchor == "t"} == {"w"}


def test_the_holdout_split_is_stable_nested_and_near_its_share():
    names = [f"tag-{i}" for i in range(4000)]
    held = {n for n in names if is_held_out_tag(n)}
    assert abs(len(held) / len(names) * 100 - HOLDOUT_PERCENT) < 2.0
    assert {n for n in names if is_held_out_tag(n, 10)} < held
    assert not any(is_held_out_tag(n, 0) for n in names)


def test_recall_is_capped_so_a_big_tag_is_not_punished_for_its_size():
    from train.eval import metrics

    gold = frozenset(f"g{i}" for i in range(400))
    m = metrics(["x", *[f"g{i}" for i in range(99)]], gold)
    assert m == {"mrr": 0.5, "p_at_10": 0.9, "recall_at_100": 0.99}
