"""Tests for how a tag is turned into training anchors.

The bug these pin down: the dataset previously taught a tag *only* through
"name. description". The bare name — the string a player actually types — was
never an anchor, so "mana dork" was left to whatever else happened to use those
words. In the shipped model it had been claimed by a template rule matching
"Add one green mana", which also fires on lands, so the query returned lands.
"""

from __future__ import annotations

import pytest

from ot_backend.semantic.dataset_service import _tag_anchors


def test_a_described_tag_is_taught_by_both_forms() -> None:
    anchors = _tag_anchors("mana dork", "Low-cost creatures which can repeatedly generate mana")

    assert anchors == [
        "mana dork",
        "mana dork. Low-cost creatures which can repeatedly generate mana",
    ]


def test_the_bare_name_is_always_first() -> None:
    """It is the query form, so it must exist even when a description does."""
    for name, desc in [("wrath", "Board wipes."), ("cantrip", "Draws a card.")]:
        assert _tag_anchors(name, desc)[0] == name


def test_an_undescribed_tag_yields_one_anchor() -> None:
    """71% of card tags have no description; they must not emit a duplicate."""
    assert _tag_anchors("mana dork", None) == ["mana dork"]
    assert _tag_anchors("mana dork", "") == ["mana dork"]


@pytest.mark.parametrize("raw", ["mana-dork", "mana_dork", "mana dork"])
def test_separators_normalize_to_the_typed_form(raw: str) -> None:
    """Scryfall slugs use hyphens; a player types spaces."""
    assert _tag_anchors(raw, None) == ["mana dork"]


def test_a_description_equal_to_the_name_is_not_duplicated() -> None:
    assert _tag_anchors("flying", "") == ["flying"]


def test_blank_tag_names_produce_no_anchor() -> None:
    assert _tag_anchors("  ", None) == []


# ---------------------------------------------------------------------------
# Hard-negative mining
# ---------------------------------------------------------------------------


def test_negatives_come_from_co_occurring_tags_not_the_tag_itself() -> None:
    """A negative must be adjacent but definitively outside the tag."""
    from ot_backend.semantic.dataset_service import build_hard_negative_pools

    dorks = [("dork%d" % i, 0) for i in range(4)]
    tag_to_faces = {
        "mana dork": dorks,
        # overlaps on 3 dorks, so it clears the min-overlap floor; the rocks are
        # the useful contrast — mana sources that are not dorks.
        "adds multiple mana": [*dorks[:3], ("rock1", 0), ("rock2", 0)],
        "unrelated": [("far1", 0)],
    }

    pools = build_hard_negative_pools(tag_to_faces)

    assert set(pools["mana dork"]) == {("rock1", 0), ("rock2", 0)}
    assert not set(pools["mana dork"]) & set(dorks), "a member can never be its own negative"
    assert ("far1", 0) not in pools["mana dork"], "no shared tag means it is not adjacent"


def test_a_single_coincidental_overlap_is_not_enough() -> None:
    """One shared card between two tags is noise, not a relationship."""
    from ot_backend.semantic.dataset_service import build_hard_negative_pools

    pools = build_hard_negative_pools(
        {"a": [("x", 0), ("a1", 0)], "b": [("x", 0), ("b1", 0), ("b2", 0)]}
    )

    assert pools["a"] == []


def test_a_specifically_related_tag_outranks_a_generic_one() -> None:
    """Ranking by raw overlap would draw negatives from huge generic tags."""
    from ot_backend.semantic.dataset_service import build_hard_negative_pools

    members = [("m%d" % i, 0) for i in range(10)]
    generic = [*members, *[("g%d" % i, 0) for i in range(500)]]   # overlaps 10, huge
    specific = [*members[:5], ("s1", 0), ("s2", 0)]               # overlaps 5, tight

    pools = build_hard_negative_pools(
        {"t": members, "activated ability": generic, "adds multiple mana": specific}
    )

    assert pools["t"][0] in {("s1", 0), ("s2", 0)}, "the tightly-associated tag must rank first"


def test_a_tag_with_no_co_occurrence_yields_an_empty_pool() -> None:
    from ot_backend.semantic.dataset_service import build_hard_negative_pools

    pools = build_hard_negative_pools({"lonely": [("a", 0)], "other": [("b", 0)]})

    assert pools["lonely"] == []


def test_pools_are_bounded() -> None:
    """Mining runs over every tag, so it must not blow up on the head tags."""
    from ot_backend.semantic.dataset_service import (
        _HARD_NEGATIVE_POOL_CAP,
        build_hard_negative_pools,
    )

    big = [(f"c{i}", 0) for i in range(5000)]
    pools = build_hard_negative_pools({"t": [("shared", 0)], "huge": [("shared", 0), *big]})

    assert len(pools["t"]) <= _HARD_NEGATIVE_POOL_CAP
