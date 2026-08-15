"""Tests for per-ability search tuning (force / reject on the seed face).

Scoring is exercised against the testcontainer Postgres with a fake
`SemanticIndex` (no ONNX): vectors are seeded directly, so every similarity in
here is one this file chose. The catalog is built from a four-ability
vocabulary, plus one vector deliberately blended to sit inside the rejection
band, so the band's ramp can be asserted numerically rather than by eyeball.
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

_MODEL_ID = "m-tuning-test"
_DIM = 384

# Ability vocabulary. 0-3 are independent draws (near-orthogonal in 384-d, so
# cosine ~0); "band" is blended to sit at exactly 0.80 against ability 2, i.e.
# halfway through the 0.70-0.90 rejection ramp.
_BAND_SIMILARITY = 0.80
_ABILITIES = ("a0", "a1", "a2", "a3", "band")

# oracle_id -> abilities it prints, in order.
_FACES = {
    "seed": ("a0", "a1", "a2"),
    "both": ("a0", "a1"),          # exactly what the seed wants, nothing else
    "same": ("a0", "a1", "a2"),    # identical to the seed
    "near": ("a0", "a1", "band"),  # a2 restated closely enough to land in the band
    "extra": ("a0", "a1", "a3"),   # both wanted abilities plus an unrelated one
    "other": ("a3",),              # unrelated
}


def _unit(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(_DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _blend(base: np.ndarray, cosine: float) -> np.ndarray:
    """A unit vector at exactly `cosine` from `base`."""
    orthogonal = _unit(seed=99)
    orthogonal = orthogonal - float(orthogonal @ base) * base
    orthogonal /= np.linalg.norm(orthogonal)
    blended = cosine * base + np.sqrt(1.0 - cosine**2) * orthogonal
    return (blended / np.linalg.norm(blended)).astype(np.float32)


def _vectors() -> dict[str, np.ndarray]:
    vectors = {name: _unit(seed=i) for i, name in enumerate(_ABILITIES[:4])}
    vectors["band"] = _blend(vectors["a2"], _BAND_SIMILARITY)
    return vectors


def _hash(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def _raw(oracle_id: str, n: int) -> CardRaw:
    return CardRaw(
        id=f"s-{oracle_id}", oracle_id=oracle_id, name=oracle_id, lang="en", layout="normal",
        color_identity=[], keywords=[], legalities={}, rarity="common", set_code="tst",
        set_id="set-tst", set_name="Test Set", set_type="expansion", collector_number=str(n),
        games=["paper"], finishes=["nonfoil"],
    )


@pytest.fixture()
def tuning_db():
    init_db()
    vectors = _vectors()
    with SessionLocal() as db:
        for i, (oracle_id, abilities) in enumerate(_FACES.items()):
            db.add(_raw(oracle_id, i + 1))
            db.add(
                Card(
                    oracle_id=oracle_id, scryfall_id=f"s-{oracle_id}", name=oracle_id,
                    layout="normal", cmc=1.0, color_identity=[], legalities={},
                    edhrec_rank=i + 1, rarity="common",
                )
            )
            db.flush()
            db.add(
                CardFace(
                    oracle_id=oracle_id, face_ix=0, name=oracle_id, type_line="Creature",
                    colors=[], type_categories=["creature"], cmc=1.0,
                )
            )
            for ability_ix, ability in enumerate(abilities):
                db.add(
                    CardFaceAbility(
                        oracle_id=oracle_id, face_ix=0, ability_ix=ability_ix,
                        text=ability, normalized_text=ability, text_hash=_hash(ability),
                        # a0 stands in for a bare keyword so the ignore_keywords
                        # interaction has something to bite on.
                        is_keyword=ability == "a0",
                    )
                )
        db.add(
            SemanticModel(
                id=_MODEL_ID, slug="tuning-test", base_model="all-MiniLM-L6-v2",
                status="ready", is_active=True, embedding_dim=_DIM,
            )
        )
        db.flush()
        for name, vector in vectors.items():
            db.add(
                SemanticAbilityEmbedding(
                    model_id=_MODEL_ID, text_hash=_hash(name), embedding=vector.tolist()
                )
            )
        db.commit()

    yield

    with SessionLocal() as db:
        for model in (
            SemanticAbilityEmbedding, CardFaceAbility, SemanticModelArtifact,
            SemanticModel, CardFace, Card, CardRaw, SystemMetadata,
        ):
            db.query(model).delete()
        db.commit()


def _index() -> SemanticIndex:
    """A SemanticIndex without __init__, so no ONNX bundle is needed."""
    index = object.__new__(SemanticIndex)
    index.model_id = _MODEL_ID
    index._idf = None
    return index


def _hits(**kwargs) -> dict[str, float]:
    with SessionLocal() as db:
        results = _index().similar_to_face(("seed", 0), limit=20, db=db, **kwargs)
    return {hit.face_key[0]: hit.score for hit in results}


# ---------------------------------------------------------------------------
# Seed selection
# ---------------------------------------------------------------------------


def test_forcing_every_ability_is_identical_to_no_tuning(tuning_db) -> None:
    """Selecting everything narrows nothing, so it must not change the search."""
    assert _hits(include_abilities=[0, 1, 2]) == _hits()


def test_forcing_a_subset_stops_punishing_unrelated_extra_abilities(tuning_db) -> None:
    """Untuned scoring is bidirectional; a hand-picked subset is forward-only.

    `extra` prints both wanted abilities plus an unrelated one. Untuned that
    unrelated ability drags it below `both`; once the user has asked for
    abilities 0 and 1 specifically, it must not.
    """
    untuned = _hits()
    assert untuned["extra"] < untuned["both"]

    forced = _hits(include_abilities=[0, 1])
    assert forced["extra"] == pytest.approx(forced["both"], abs=1e-6)


def test_rejecting_an_ability_drops_it_from_the_seed(tuning_db) -> None:
    """`near` only ranks if ability 2 stopped being something we search by."""
    hits = _hits(exclude_abilities=[2])
    assert "both" in hits
    # Ability 2 is gone from the seed, so `both` is a complete match again.
    assert hits["both"] == pytest.approx(1.0, abs=1e-6)


def test_rejecting_every_ability_returns_nothing(tuning_db) -> None:
    assert _hits(exclude_abilities=[0, 1, 2]) == {}


def test_forcing_and_rejecting_together(tuning_db) -> None:
    """The "1 and 2 but not 3" case: seed is exactly {0}, ability 2 rejected."""
    hits = _hits(include_abilities=[0], exclude_abilities=[2])
    assert "same" not in hits                                   # prints the rejected ability
    assert hits["both"] == pytest.approx(1.0, abs=1e-6)         # forced ability fully matched
    assert hits["near"] == pytest.approx(0.5, rel=0.02)         # mid-band restatement, halved
    # Stage 1 is a top-N probe, not a threshold, so in a catalog this small even
    # an unrelated face is a candidate — it just scores near zero.
    assert hits["other"] < 0.1


# ---------------------------------------------------------------------------
# Rejection band
# ---------------------------------------------------------------------------


def test_exact_match_on_a_rejected_ability_is_dropped(tuning_db) -> None:
    assert "same" in _hits()
    assert "same" not in _hits(exclude_abilities=[2])


def test_near_match_on_a_rejected_ability_is_scaled_not_dropped(tuning_db) -> None:
    """0.80 sits halfway through the 0.70-0.90 ramp, so the score halves."""
    hits = _hits(exclude_abilities=[2])
    assert hits["near"] == pytest.approx(hits["both"] * 0.5, rel=0.02)


def test_unrelated_cards_are_not_scaled_by_a_rejection(tuning_db) -> None:
    """Below the 0.70 floor the penalty is inert, so scores are untouched."""
    baseline = _hits(include_abilities=[0, 1])
    rejected = _hits(include_abilities=[0, 1], exclude_abilities=[2])
    assert rejected["both"] == pytest.approx(baseline["both"], abs=1e-6)


# ---------------------------------------------------------------------------
# ignore_keywords interaction
# ---------------------------------------------------------------------------


def test_forced_keyword_seeds_the_search_even_with_ignore_keywords(tuning_db) -> None:
    """The seed load is by index alone, so the keyword filter can't drop it.

    Candidate generation still honours `ignore_keywords`, so matches can only
    come back through non-keyword abilities — the two controls are independent
    on purpose, and this pins that split down.
    """
    with SessionLocal() as db:
        index = _index()
        seed = index._load_face_abilities(db, ("seed", 0), ability_ixs=[0])
        assert seed is not None and seed[2] == [0]

        keyword_filtered = index._load_face_abilities(db, ("seed", 0), ignore_keywords=True)
        assert keyword_filtered is not None and 0 not in keyword_filtered[2]


def test_ignore_keywords_alone_keeps_bidirectional_scoring(tuning_db) -> None:
    """`noKw` is not a hand-picked subset, so it must not flip the pooling.

    If it did, `extra` would tie with `both` the way it does under an explicit
    force (see `test_forcing_a_subset_...`) instead of being demoted for its
    unrelated third ability.
    """
    hits = _hits(ignore_keywords=True)
    assert hits["extra"] < hits["both"]
