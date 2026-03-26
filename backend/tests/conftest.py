import os
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ORACLE_TUTOR_API_UPDATE_ENABLED", "false")

# Ensure the `src/` layout package is importable when running pytest without an editable install.
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from ot_backend.api.main import app  # noqa: E402
from ot_backend.core.database import SessionLocal  # noqa: E402
from ot_backend.core.db_init import init_db  # noqa: E402
from ot_backend.core.models import Card, CardFace, CardRaw  # noqa: E402


def _make_card_raw(
    *,
    scryfall_id: str,
    oracle_id: str,
    name: str,
    collector_number: str,
    layout: str = "normal",
    keywords: list[str] | None = None,
) -> CardRaw:
    return CardRaw(
        id=scryfall_id,
        oracle_id=oracle_id,
        name=name,
        lang="en",
        layout=layout,
        color_identity=[],
        keywords=keywords or [],
        legalities={},
        rarity="common",
        set_code="tst",
        set_id="set-tst",
        set_name="Test Set",
        set_type="expansion",
        collector_number=collector_number,
        games=["paper"],
        finishes=["nonfoil"],
    )


def _seed_db() -> None:
    init_db()
    with SessionLocal() as db:
        # Clean slate (sqlite :memory: persists across tests with StaticPool)
        db.query(CardFace).delete()
        db.query(Card).delete()
        db.query(CardRaw).delete()
        db.commit()

        db.add_all(
            [
                _make_card_raw(scryfall_id="s1", oracle_id="o1", name="Lightning Bolt", collector_number="1"),
                _make_card_raw(scryfall_id="s2", oracle_id="o2", name="Shock", collector_number="2", keywords=["Deathtouch"]),
                _make_card_raw(scryfall_id="s3", oracle_id="o3", name="Giant Growth", collector_number="3", keywords=["Trample", "Vigilance"]),
                _make_card_raw(scryfall_id="s4", oracle_id="o4", name="Verbose Shock", collector_number="4"),
                _make_card_raw(scryfall_id="s5", oracle_id="o5", name="Red Artifact", collector_number="5"),
                _make_card_raw(
                    scryfall_id="s6",
                    oracle_id="o6",
                    name="Fire // Ice",
                    collector_number="6",
                    layout="split",
                ),
                _make_card_raw(
                    scryfall_id="s7",
                    oracle_id="o7",
                    name="Brutal Cathar // Moonrage Brute",
                    collector_number="7",
                    layout="transform",
                ),
                _make_card_raw(
                    scryfall_id="s8",
                    oracle_id="o8",
                    name="Aang, at the Crossroads // Aang, Destined Savior",
                    collector_number="8",
                    layout="transform",
                ),
            ]
        )
        bolt = Card(oracle_id="o1", scryfall_id="s1", name="Lightning Bolt", layout="normal", edhrec_rank=1, rarity="common", legalities={}, color_identity=["R"])
        shock = Card(oracle_id="o2", scryfall_id="s2", name="Shock", layout="normal", edhrec_rank=2, rarity="common", legalities={}, color_identity=["R"])
        growth = Card(oracle_id="o3", scryfall_id="s3", name="Giant Growth", layout="normal", edhrec_rank=3, rarity="common", legalities={}, color_identity=["G"])
        verbose_shock = Card(oracle_id="o4", scryfall_id="s4", name="Verbose Shock", layout="normal", edhrec_rank=4, rarity="common", legalities={}, color_identity=["R"])
        artifact = Card(oracle_id="o5", scryfall_id="s5", name="Red Artifact", layout="normal", edhrec_rank=5, rarity="common", legalities={}, color_identity=["R"])
        split_card = Card(oracle_id="o6", scryfall_id="s6", name="Fire // Ice", layout="split", edhrec_rank=6, rarity="uncommon", legalities={}, color_identity=["R", "U"])
        transform_card = Card(oracle_id="o7", scryfall_id="s7", name="Brutal Cathar // Moonrage Brute", layout="transform", edhrec_rank=7, rarity="rare", legalities={}, color_identity=["W"])
        aang_card = Card(oracle_id="o8", scryfall_id="s8", name="Aang, at the Crossroads // Aang, Destined Savior", layout="transform", edhrec_rank=8, rarity="mythic", legalities={}, color_identity=["W", "U", "R"])
        db.add_all([bolt, shock, growth, verbose_shock, artifact, split_card, transform_card, aang_card])
        db.flush()

        db.add_all(
            [
                CardFace(
                    oracle_id="o1",
                    face_ix=0,
                    name="Lightning Bolt",
                    type_line="Instant",
                    oracle_text="Lightning Bolt deals 3 damage to any target.",
                    colors=["R"],
                ),
                CardFace(
                    oracle_id="o2",
                    face_ix=0,
                    name="Shock",
                    type_line="Instant",
                    oracle_text="Shock deals 2 damage to any target.",
                    colors=["R"],
                ),
                CardFace(
                    oracle_id="o3",
                    face_ix=0,
                    name="Giant Growth",
                    type_line="Instant",
                    oracle_text="Target creature gets +3/+3 until end of turn.",
                    colors=["G"],
                ),
                CardFace(
                    oracle_id="o4",
                    face_ix=0,
                    name="Verbose Shock",
                    type_line="Instant",
                    oracle_text=(
                        "Shock deals 2 damage to any target.\n"
                        "Draw a card.\n"
                        "Then discard a card."
                    ),
                    colors=["R"],
                ),
                CardFace(
                    oracle_id="o5",
                    face_ix=0,
                    name="Red Artifact",
                    type_line="Artifact",
                    oracle_text="Landfall — {R}: Deal 1 damage.",
                    colors=[],
                ),
                CardFace(
                    oracle_id="o6",
                    face_ix=0,
                    name="Fire",
                    type_line="Instant",
                    oracle_text="Fire deals 2 damage divided as you choose among one or two targets.",
                    colors=["R"],
                ),
                CardFace(
                    oracle_id="o6",
                    face_ix=1,
                    name="Ice",
                    type_line="Instant",
                    oracle_text="Tap target permanent. Draw a card.",
                    colors=["U"],
                ),
                CardFace(
                    oracle_id="o7",
                    face_ix=0,
                    name="Brutal Cathar",
                    type_line="Creature — Human Soldier Werewolf",
                    oracle_text="When this creature enters, exile target creature an opponent controls.",
                    colors=["W"],
                ),
                CardFace(
                    oracle_id="o7",
                    face_ix=1,
                    name="Moonrage Brute",
                    type_line="Creature — Werewolf",
                    oracle_text="At the beginning of each upkeep, if a player cast no spells last turn, transform Moonrage Brute.",
                    colors=["W"],
                ),
                CardFace(
                    oracle_id="o8",
                    face_ix=0,
                    name="Aang, at the Crossroads",
                    type_line="Legendary Creature",
                    oracle_text="Front face text.",
                    colors=["W", "U", "R"],
                ),
                CardFace(
                    oracle_id="o8",
                    face_ix=1,
                    name="Aang, Destined Savior",
                    type_line="Legendary Creature",
                    oracle_text="Back face text.",
                    colors=["W", "U", "R"],
                ),
            ]
        )
        db.commit()


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    _seed_db()
    with TestClient(app) as c:
        yield c
