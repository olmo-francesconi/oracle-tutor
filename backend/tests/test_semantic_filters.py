"""Tests for the SQL filter path on the semantic index.

These exercise `SemanticIndex._score` end-to-end against the testcontainer
Postgres (pgvector + JSONB + ARRAY). The ONNX encoder is bypassed entirely —
we construct a fake `SemanticIndex` with only `model_id` set and call `_score`
directly, so the tests cover what the SQL emits, not the model.

Each seeded card has exactly one ability, so filter results are unchanged by
the ability layer: one face still maps to one vector.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from ot_backend.core.database import SessionLocal
from ot_backend.core.db_init import init_db
from ot_backend.core.models import (
    Card,
    CardFace,
    CardFaceAbility,
    CardRaw,
    SemanticAbilityEmbedding,
    SemanticModel,
    SemanticModelArtifact,
    SystemMetadata,
)
from ot_backend.semantic.index import SemanticIndex

_MODEL_ID = "m-filter-test"
_DIM = 384


def _vec(seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(_DIM).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tolist()


def _hash(i: int) -> str:
    return hashlib.sha256(f"ability {i}".encode()).hexdigest()


def _truncate(db) -> None:
    db.query(SemanticAbilityEmbedding).delete()
    db.query(CardFaceAbility).delete()
    db.query(SemanticModelArtifact).delete()
    db.query(SemanticModel).delete()
    db.query(CardFace).delete()
    db.query(Card).delete()
    db.query(CardRaw).delete()
    db.query(SystemMetadata).delete()
    db.commit()


def _raw(scryfall_id: str, oracle_id: str, name: str, n: str) -> CardRaw:
    return CardRaw(
        id=scryfall_id,
        oracle_id=oracle_id,
        name=name,
        lang="en",
        layout="normal",
        color_identity=[],
        keywords=[],
        legalities={},
        rarity="common",
        set_code="tst",
        set_id="set-tst",
        set_name="Test Set",
        set_type="expansion",
        collector_number=n,
        games=["paper"],
        finishes=["nonfoil"],
    )


@pytest.fixture()
def seeded_filter_db():
    """Seed a small, deterministic catalog and one active semantic model.

    Cards span every filter dimension (type, colors, identity, cmc, rarity,
    legalities) so each filter assertion has both matches and non-matches.
    """
    init_db()
    with SessionLocal() as db:
        _truncate(db)

        cards: list[tuple[str, str, dict]] = [
            # (oracle_id, scryfall_id, fields)
            (
                "f1",
                "fs1",
                dict(
                    name="Bolt",
                    rarity="common",
                    cmc=1.0,
                    color_identity=["R"],
                    legalities={"standard": "legal", "modern": "legal"},
                    face_colors=["R"],
                    face_types=["instant"],
                ),
            ),
            (
                "f2",
                "fs2",
                dict(
                    name="Counterspell",
                    rarity="uncommon",
                    cmc=2.0,
                    color_identity=["U"],
                    legalities={"modern": "legal", "legacy": "legal"},
                    face_colors=["U"],
                    face_types=["instant"],
                ),
            ),
            (
                "f3",
                "fs3",
                dict(
                    name="Wrath",
                    rarity="rare",
                    cmc=4.0,
                    color_identity=["W"],
                    legalities={"legacy": "legal", "vintage": "restricted"},
                    face_colors=["W"],
                    face_types=["sorcery"],
                ),
            ),
            (
                "f4",
                "fs4",
                dict(
                    name="Bear",
                    rarity="common",
                    cmc=2.0,
                    color_identity=["G"],
                    legalities={"standard": "legal"},
                    face_colors=["G"],
                    face_types=["creature"],
                ),
            ),
            (
                "f5",
                "fs5",
                dict(
                    name="Dragon",
                    rarity="mythic",
                    cmc=6.0,
                    color_identity=["R", "W"],
                    legalities={"commander": "legal"},
                    face_colors=["R", "W"],
                    face_types=["creature"],
                ),
            ),
            (
                "f6",
                "fs6",
                dict(
                    name="Artifact",
                    rarity="rare",
                    cmc=3.0,
                    color_identity=[],
                    legalities={"standard": "legal", "modern": "legal", "commander": "legal"},
                    face_colors=[],
                    face_types=["artifact"],
                ),
            ),
            (
                "f7",
                "fs7",
                dict(
                    name="Banned Card",
                    rarity="rare",
                    cmc=2.0,
                    color_identity=["B"],
                    legalities={"modern": "banned", "legacy": "banned"},
                    face_colors=["B"],
                    face_types=["sorcery"],
                ),
            ),
        ]

        db.add_all([_raw(scryfall_id, oracle_id, fields["name"], str(i + 1)) for i, (oracle_id, scryfall_id, fields) in enumerate(cards)])
        db.add_all(
            [
                Card(
                    oracle_id=oracle_id,
                    scryfall_id=scryfall_id,
                    name=fields["name"],
                    layout="normal",
                    cmc=fields["cmc"],
                    color_identity=fields["color_identity"],
                    legalities=fields["legalities"],
                    edhrec_rank=i + 1,
                    rarity=fields["rarity"],
                )
                for i, (oracle_id, scryfall_id, fields) in enumerate(cards)
            ]
        )
        db.flush()

        db.add_all(
            [
                CardFace(
                    oracle_id=oracle_id,
                    face_ix=0,
                    name=fields["name"],
                    type_line=fields["face_types"][0],
                    colors=fields["face_colors"],
                    type_categories=fields["face_types"],
                    cmc=fields["cmc"],
                )
                for oracle_id, _scryfall_id, fields in cards
            ]
        )

        db.add(
            SemanticModel(
                id=_MODEL_ID,
                slug="filter-test-model",
                base_model="all-MiniLM-L6-v2",
                status="ready",
                is_active=True,
                embedding_dim=_DIM,
            )
        )
        db.flush()

        # One distinct ability per card; the hash is the join key between the
        # ability row and its vector.
        db.add_all(
            [
                CardFaceAbility(
                    oracle_id=oracle_id,
                    face_ix=0,
                    ability_ix=0,
                    text=f"ability {i}",
                    normalized_text=f"ability {i}",
                    text_hash=_hash(i),
                )
                for i, (oracle_id, _scryfall_id, _fields) in enumerate(cards)
            ]
        )
        db.add_all(
            [
                SemanticAbilityEmbedding(
                    model_id=_MODEL_ID,
                    text_hash=_hash(i),
                    embedding=_vec(seed=i),
                )
                for i in range(len(cards))
            ]
        )
        db.commit()

    yield

    with SessionLocal() as db:
        _truncate(db)


def _ids(results) -> set[tuple[str, int]]:
    return {hit.face_key for hit in results}


def _make_index(model_id: str | None = _MODEL_ID) -> SemanticIndex:
    """Build a SemanticIndex without going through __init__ (no ONNX needed)."""
    idx = object.__new__(SemanticIndex)
    idx.model_id = model_id
    return idx


def _seed():
    """A single synthetic query vector, shaped as the (1, dim) seed set."""
    return np.asarray([_vec(seed=999)], dtype=np.float32)


def _score(db, **filters):
    """Drive the ability-level scorer with a single synthetic query vector."""
    return _make_index()._score(db, _seed(), limit=100, bidirectional=False, **filters)


def test_no_filters_returns_every_face(seeded_filter_db) -> None:
    with SessionLocal() as db:
        results = _score(db)
    assert _ids(results) == {(f"f{i}", 0) for i in range(1, 8)}


def test_card_type_filter_uses_array_overlap(seeded_filter_db) -> None:
    with SessionLocal() as db:
        results = _score(db, card_type=["creature"])
    assert _ids(results) == {("f4", 0), ("f5", 0)}


def test_card_type_filter_multiple_types(seeded_filter_db) -> None:
    with SessionLocal() as db:
        results = _score(db, card_type=["instant", "artifact"])
    assert _ids(results) == {("f1", 0), ("f2", 0), ("f6", 0)}


def test_cmc_range_inclusive(seeded_filter_db) -> None:
    with SessionLocal() as db:
        results = _score(db, cmc_min=2.0, cmc_max=3.0)
    assert _ids(results) == {("f2", 0), ("f4", 0), ("f6", 0), ("f7", 0)}


def test_rarity_filter(seeded_filter_db) -> None:
    with SessionLocal() as db:
        results = _score(db, rarity=["rare", "mythic"])
    assert _ids(results) == {("f3", 0), ("f5", 0), ("f6", 0), ("f7", 0)}


def test_format_filter_legal_only(seeded_filter_db) -> None:
    # f7 is "banned" in modern — must be excluded.
    with SessionLocal() as db:
        results = _score(db, format=["modern"])
    assert _ids(results) == {("f1", 0), ("f2", 0), ("f6", 0)}


def test_format_filter_restricted_counts_as_eligible(seeded_filter_db) -> None:
    # f3 is "restricted" in vintage — should be eligible.
    with SessionLocal() as db:
        results = _score(db, format=["vintage"])
    assert _ids(results) == {("f3", 0)}


def test_format_filter_multiple_formats_or(seeded_filter_db) -> None:
    with SessionLocal() as db:
        results = _score(db, format=["standard", "commander"])
    assert _ids(results) == {("f1", 0), ("f4", 0), ("f5", 0), ("f6", 0)}


def test_color_identity_at_least(seeded_filter_db) -> None:
    # at_least R: every card whose color_identity contains R.
    with SessionLocal() as db:
        results = _score(db, colors="R", color_feature="identity", match_mode="at_least")
    assert _ids(results) == {("f1", 0), ("f5", 0)}


def test_color_identity_at_least_multi(seeded_filter_db) -> None:
    # at_least RW: identity must contain both R and W.
    with SessionLocal() as db:
        results = _score(db, colors="RW", color_feature="identity", match_mode="at_least")
    assert _ids(results) == {("f5", 0)}


def test_color_identity_at_most(seeded_filter_db) -> None:
    # at_most RW: identity is a subset of {R, W} (includes colorless).
    with SessionLocal() as db:
        results = _score(db, colors="RW", color_feature="identity", match_mode="at_most")
    assert _ids(results) == {("f1", 0), ("f3", 0), ("f5", 0), ("f6", 0)}


def test_color_identity_exact(seeded_filter_db) -> None:
    with SessionLocal() as db:
        results = _score(db, colors="RW", color_feature="identity", match_mode="exact")
    assert _ids(results) == {("f5", 0)}


def test_color_face_filter(seeded_filter_db) -> None:
    with SessionLocal() as db:
        results = _score(db, colors="U", color_feature="colors", match_mode="at_least")
    assert _ids(results) == {("f2", 0)}


def test_invalid_color_chars_skip_filter(seeded_filter_db) -> None:
    # Matches the old bitmask behavior: invalid chars → no filter applied.
    with SessionLocal() as db:
        results = _score(db, colors="XYZ")
    assert _ids(results) == {(f"f{i}", 0) for i in range(1, 8)}


def test_exclude_seed_face(seeded_filter_db) -> None:
    with SessionLocal() as db:
        results = _make_index()._score(
            db, _seed(), limit=100, bidirectional=False, exclude=("f3", 0)
        )
    assert ("f3", 0) not in _ids(results)
    assert len(results) == 6


def test_combined_filters(seeded_filter_db) -> None:
    # rare creatures in commander with cmc >= 5 → only Dragon (f5).
    with SessionLocal() as db:
        results = _score(
            db,
            card_type=["creature"],
            cmc_min=5.0,
            rarity=["mythic"],
            format=["commander"],
            colors="R",
            color_feature="identity",
            match_mode="at_least",
        )
    assert _ids(results) == {("f5", 0)}


def test_scores_are_in_descending_order(seeded_filter_db) -> None:
    with SessionLocal() as db:
        results = _score(db)
    scores = [hit.score for hit in results]
    assert scores == sorted(scores, reverse=True)


def test_limit_is_applied(seeded_filter_db) -> None:
    with SessionLocal() as db:
        results = _make_index()._score(db, _seed(), limit=3, bidirectional=False)
    assert len(results) == 3


def test_no_model_id_returns_empty(seeded_filter_db) -> None:
    with SessionLocal() as db:
        results = _make_index(model_id=None)._score(db, _seed(), limit=10, bidirectional=False)
    assert results == []


def test_zero_limit_returns_empty(seeded_filter_db) -> None:
    with SessionLocal() as db:
        results = _score(db)
    assert _ids(results)  # sanity: default is populated

    with SessionLocal() as db:
        results = _make_index()._score(db, _seed(), limit=0, bidirectional=False)
    assert results == []


# ---------------------------------------------------------------------------
# Completeness: retrieval must not drop anything eligible
# ---------------------------------------------------------------------------


def test_a_barely_similar_face_is_still_returned(seeded_filter_db) -> None:
    """The guarantee is completeness, not a similarity threshold.

    Seeds are random unit vectors, so most faces sit near zero similarity to the
    query. Every one of them must still come back — the old two-stage path cut
    to the 256 nearest ability texts first, and anything past that was not
    ranked low, it was never considered.
    """
    with SessionLocal() as db:
        results = _score(db)

    assert len(results) == 7
    assert min(hit.score for hit in results) < 0.2, "expected genuinely weak matches in the set"


def test_a_filter_is_applied_before_any_truncation(seeded_filter_db) -> None:
    """A filter must never be able to empty the result set on its own.

    This is the shape of the shipped bug: filters ran after the kNN cut, so a
    filter anticorrelated with the query returned almost nothing even when
    thousands of cards qualified.
    """
    with SessionLocal() as db:
        every = _score(db)
        creatures = _score(db, card_type=["creature"])

    assert _ids(creatures) == {("f4", 0), ("f5", 0)}
    assert _ids(creatures) <= _ids(every)
    assert all(hit.score == pytest.approx(dict((h.face_key, h.score) for h in every)[hit.face_key])
               for hit in creatures), "filtering must not change a face's score"


def test_the_mask_cache_does_not_leak_between_filters(seeded_filter_db) -> None:
    """Masks are memoized per filter combination; the key must separate them."""
    index = _make_index()
    with SessionLocal() as db:
        creatures = index._score(db, _seed(), limit=100, bidirectional=False, card_type=["creature"])
        instants = index._score(db, _seed(), limit=100, bidirectional=False, card_type=["instant"])
        again = index._score(db, _seed(), limit=100, bidirectional=False, card_type=["creature"])

    assert _ids(creatures) != _ids(instants)
    assert _ids(creatures) == _ids(again)
