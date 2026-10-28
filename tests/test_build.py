import json
from pathlib import Path

import pytest

from app.build import build_cards, iter_bulk, select_best_printing, type_categories
from app.text import EMPTY_ORACLE_TOKEN

FIXTURE = Path(__file__).parent / "fixtures" / "scryfall_sample.jsonl"


@pytest.fixture(scope="module")
def built():
    cards, texts = build_cards(iter_bulk(str(FIXTURE)))
    return {c["name"]: c for c in cards}, texts


def test_select_best_printing_prefers_paper_over_digital():
    paper = {"id": "1", "games": ["paper"], "released_at": "2020-01-01"}
    digital = {"id": "2", "games": ["mtgo"], "released_at": "2010-01-01"}
    assert select_best_printing(paper, digital) is paper
    assert select_best_printing(digital, paper) is paper


def test_select_best_printing_prefers_older_then_lower_collector_number():
    old = {"games": ["paper"], "released_at": "2000-01-01"}
    new = {"games": ["paper"], "released_at": "2020-01-01"}
    assert select_best_printing(new, old) is old
    a = {"games": ["paper"], "released_at": "2020-01-01", "collector_number": "10"}
    b = {"games": ["paper"], "released_at": "2020-01-01", "collector_number": "9"}
    assert select_best_printing(a, b) is b  # numeric, not lexicographic
    assert select_best_printing({"id": "1"}, {"id": "2"})["id"] == "1"


def test_one_card_per_oracle_id_with_best_printing(built):
    cards, _ = built
    assert len(cards) == len({json.loads(line)["oracle_id"] for line in FIXTURE.open()})
    assert (cards["Abzan Charm"]["set_code"], cards["Abzan Charm"]["cmc"]) == ("ktk", 3.0)
    assert cards["Grizzly Bears"]["set_code"] == "ced"


def test_card_is_v2_card_body_plus_internal_fields(built):
    card = built[0]["Abzan Charm"]
    assert [k for k in card if not k.startswith("_")] == [
        "oracle_id", "scryfall_id", "name", "layout", "cmc", "edhrec_rank", "rarity", "legalities",
        "set_code", "border_color", "faces",
    ]
    assert card["_color_identity"] == "WBG"
    assert built[0]["Serra Angel"]["_keywords"] == ["Flying", "Vigilance"]


def test_transform_dfc_has_two_faces(built):
    card = built[0]["Delver of Secrets // Insectile Aberration"]
    assert [f["name"] for f in card["faces"]] == ["Delver of Secrets", "Insectile Aberration"]
    assert [f["face_ix"] for f in card["faces"]] == [0, 1]
    assert card["faces"][1]["colors"] == ["U"] and card["faces"][1]["color_indicator"] == ["U"]
    assert card["faces"][0]["_type_categories"] == ["creature"]


def test_split_card_faces(built):
    card = built[0]["Fire // Ice"]
    assert [(f["name"], f["mana_cost"]) for f in card["faces"]] == [("Fire", "{1}{R}"), ("Ice", "{1}{U}")]
    assert all(f["_type_categories"] == ["instant"] for f in card["faces"])


def test_vanilla_face_gets_placeholder_hash_but_no_abilities(built):
    cards, texts = built
    face = cards["Grizzly Bears"]["faces"][0]
    assert face["abilities"] == []
    assert len(face["_hashes"]) == 1 and texts[face["_hashes"][0]] == EMPTY_ORACLE_TOKEN


def test_keyword_line_is_split(built):
    abilities = built[0]["Questing Beast"]["faces"][0]["abilities"]
    assert [(a["text"], a["is_keyword"]) for a in abilities[:3]] == [
        ("Vigilance", True), ("deathtouch", True), ("haste", True)
    ]
    assert not abilities[3]["is_keyword"]


def test_modal_bullets_stay_with_parent(built):
    abilities = built[0]["Cryptic Command"]["faces"][0]["abilities"]
    assert len(abilities) == 1 and abilities[0]["text"].count("•") == 4


def test_hashes_align_with_abilities(built):
    cards, texts = built
    for card in cards.values():
        for face in card["faces"]:
            if face["abilities"]:
                assert len(face["_hashes"]) == len(face["abilities"])
                assert [a["ability_ix"] for a in face["abilities"]] == list(range(len(face["abilities"])))
            assert all(h in texts for h in face["_hashes"])


def test_type_categories():
    assert type_categories("Legendary Artifact Creature — Golem") == ["artifact", "creature"]
    assert type_categories("Basic Land — Island") == ["land"]
    assert type_categories(None) == []


def test_embed_reuses_known_vectors_and_encodes_only_new_text(monkeypatch):
    import numpy as np

    import app.encoder
    from app.build import embed

    encoded = []

    class FakeEncoder:
        def __init__(self, model_dir, threads=1):
            pass

        def encode(self, texts):
            encoded.extend(texts)
            return np.full((len(texts), 2), 0.5, dtype=np.float32)

    monkeypatch.setattr(app.encoder, "Encoder", FakeEncoder)
    known = {"a": np.array([1, 0], dtype=np.float16)}
    hashes, vectors = embed({"b": "new text", "a": "old text"}, Path("unused"), known)
    assert encoded == ["new text"]
    assert hashes.tolist() == ["a", "b"]
    assert vectors.tolist() == [[1, 0], [0.5, 0.5]]
