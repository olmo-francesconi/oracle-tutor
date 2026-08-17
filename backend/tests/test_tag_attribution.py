"""Tests for attributing a card-level tag to the ability that justifies it.

The bug these pin down: a tag belongs to a card, but similarity is computed over
abilities. Pairing `mana dork` with the whole of Birds of Paradise teaches the
model that it means "Flying" as much as it means the mana ability.
"""

from __future__ import annotations

from ot_backend.semantic.tag_attribution import (
    DEFAULT_MIN_MEMBERS,
    attribute_tags_to_abilities,
)


def _background(n: int = 40) -> dict[tuple[str, int, int], str]:
    """Enough corpus for the document frequencies to mean something.

    Critically it makes "flying" *common*, as it is in reality — 3,235 faces.
    A fixture where the keyword appears only on the tag's members would make it
    genuinely distinctive of the tag, and lift would be right to pick it.
    """
    corpus: dict[tuple[str, int, int], str] = {}
    for i in range(n):
        corpus[(f"flier{i}", 0, 0)] = "flying."
        corpus[(f"other{i}", 0, 0)] = "destroy target permanent."
    return corpus


def _dorks(n: int = DEFAULT_MIN_MEMBERS + 10) -> dict[tuple[str, int, int], str]:
    """Faces that tap for mana and also happen to fly."""
    corpus: dict[tuple[str, int, int], str] = {}
    for i in range(n):
        corpus[(f"dork{i}", 0, 0)] = "tap this creature: add one green mana."
        corpus[(f"dork{i}", 0, 1)] = "flying."
    return corpus


def _faces(oracle_ids: list[str]) -> list[tuple[str, int]]:
    return [(oracle_id, 0) for oracle_id in oracle_ids]


def test_a_tag_attaches_to_the_ability_that_carries_it_not_the_whole_face() -> None:
    corpus = {**_background(), **_dorks()}
    members = _faces([f"dork{i}" for i in range(DEFAULT_MIN_MEMBERS + 10)])

    picks = attribute_tags_to_abilities(corpus, {"mana dork": members})["mana dork"]

    assert picks, "the tag must resolve at all"
    assert all(ability_ix == 0 for _, _, ability_ix in picks), (
        "every pick must be the mana ability; ability 1 is 'flying' and is why "
        "pairing the tag with the whole face teaches the wrong thing"
    )


def test_a_single_ability_face_needs_no_evidence() -> None:
    """There is nothing to choose between, so it is attributed unconditionally
    even for a tag too small to compute a lift over."""
    corpus = {("solo", 0, 0): "destroy target creature."}

    picks = attribute_tags_to_abilities(corpus, {"tiny tag": [("solo", 0)]})

    assert picks["tiny tag"] == [("solo", 0, 0)]


def test_an_unseparated_face_is_dropped_rather_than_guessed() -> None:
    """Precision over recall: a wrong attribution teaches a lie, a dropped one
    costs data we have in surplus."""
    corpus = {**_background(), **_dorks()}
    members = _faces([f"dork{i}" for i in range(DEFAULT_MIN_MEMBERS + 10)])

    strict = attribute_tags_to_abilities(corpus, {"mana dork": members}, min_margin=99.0)

    assert strict["mana dork"] == []


def test_a_tag_no_ability_can_justify_is_dropped_whole() -> None:
    """`alliteration` is a property of the card's NAME. Its members share no
    ability-level concept, so nothing separates their abilities and the tag
    resolves almost none of them — including its single-ability members, which
    would otherwise be paired with text that does not explain the tag."""
    corpus = dict(_background())
    members = []
    for i in range(DEFAULT_MIN_MEMBERS + 10):
        corpus[(f"allit{i}", 0, 0)] = f"when this creature enters, draw {i} cards."
        corpus[(f"allit{i}", 0, 1)] = f"whenever this creature attacks, it gets plus {i} strength."
        members.append((f"allit{i}", 0))
    corpus[("allit-solo", 0, 0)] = "target player discards two cards."
    members.append(("allit-solo", 0))

    picks = attribute_tags_to_abilities(corpus, {"alliteration": members})

    assert picks["alliteration"] == []


def test_a_tag_smaller_than_the_floor_does_not_attribute_multi_ability_faces() -> None:
    """Below the floor the token distribution is noise, not a concept."""
    corpus = {**_background(), **_dorks(n=3)}
    members = _faces([f"dork{i}" for i in range(3)])

    picks = attribute_tags_to_abilities(corpus, {"rare tag": members})["rare tag"]

    assert picks == []


def test_an_unscoreable_ability_never_wins_on_a_fabricated_margin() -> None:
    """An ability that tokenizes to nothing cannot be scored. A prototype gave
    it a -99 sentinel, which made every ability beside it win by +100 and be
    attributed regardless of the evidence."""
    corpus = {**_background(), **_dorks()}
    members = _faces([f"dork{i}" for i in range(DEFAULT_MIN_MEMBERS + 10)])
    for oracle_id, face_ix in members:
        corpus[(oracle_id, face_ix, 2)] = "—"

    picks = attribute_tags_to_abilities(corpus, {"mana dork": members})["mana dork"]

    assert picks, "the tag must still resolve"
    assert all(ability_ix == 0 for _, _, ability_ix in picks)


def test_function_words_only_text_falls_back_to_its_raw_tokens() -> None:
    """Otherwise "End the turn." — a real ability — scores as if it were empty."""
    from ot_backend.semantic.tag_attribution import _tokenize

    assert _tokenize("of the and") == frozenset({"of", "the", "and"})
    assert _tokenize("End the turn.") >= {"end", "turn"}


def test_an_empty_corpus_is_handled() -> None:
    assert attribute_tags_to_abilities({}, {"anything": [("x", 0)]}) == {}


def test_members_absent_from_the_corpus_are_ignored() -> None:
    corpus = {("known", 0, 0): "draw a card."}

    picks = attribute_tags_to_abilities(corpus, {"t": [("known", 0), ("missing", 0)]})

    assert picks["t"] == [("known", 0, 0)]
