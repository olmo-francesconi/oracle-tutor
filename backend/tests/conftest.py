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

from ot_backend.core.database import SessionLocal
from ot_backend.core.db_init import init_db
from ot_backend.api.main import app
from ot_backend.core.models import Card, CardFace, CardRaw


def _make_card_raw(*, scryfall_id: str, oracle_id: str, name: str, collector_number: str) -> CardRaw:
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
                _make_card_raw(scryfall_id="s2", oracle_id="o2", name="Shock", collector_number="2"),
                _make_card_raw(scryfall_id="s3", oracle_id="o3", name="Giant Growth", collector_number="3"),
                _make_card_raw(scryfall_id="s4", oracle_id="o4", name="Verbose Shock", collector_number="4"),
                _make_card_raw(scryfall_id="s5", oracle_id="o5", name="Red Artifact", collector_number="5"),
            ]
        )
        bolt = Card(oracle_id="o1", scryfall_id="s1", name="Lightning Bolt", layout="normal", edhrec_rank=1, rarity="common", legalities={}, color_identity=["R"])
        shock = Card(oracle_id="o2", scryfall_id="s2", name="Shock", layout="normal", edhrec_rank=2, rarity="common", legalities={}, color_identity=["R"])
        growth = Card(oracle_id="o3", scryfall_id="s3", name="Giant Growth", layout="normal", edhrec_rank=3, rarity="common", legalities={}, color_identity=["G"])
        verbose_shock = Card(oracle_id="o4", scryfall_id="s4", name="Verbose Shock", layout="normal", edhrec_rank=4, rarity="common", legalities={}, color_identity=["R"])
        artifact = Card(oracle_id="o5", scryfall_id="s5", name="Red Artifact", layout="normal", edhrec_rank=5, rarity="common", legalities={}, color_identity=["R"])
        db.add_all([bolt, shock, growth, verbose_shock, artifact])
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
                    oracle_text="{R}: Deal 1 damage.",
                    colors=[],
                ),
            ]
        )
        db.commit()


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    _seed_db()
    with TestClient(app) as c:
        yield c
