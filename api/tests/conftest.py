import os
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("TFIDF_MIN_DF", "1")
os.environ.setdefault("ORACLE_TUTOR_API_UPDATE_ENABLED", "false")

# Ensure the `src/` layout package is importable when running pytest without an editable install.
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from oracle_tutor_api.database import SessionLocal
from oracle_tutor_api.db_init import init_db
from oracle_tutor_api.main import app
from oracle_tutor_api.models import Card, CardFace


def _seed_db() -> None:
    init_db()
    with SessionLocal() as db:
        # Clean slate (sqlite :memory: persists across tests with StaticPool)
        db.query(CardFace).delete()
        db.query(Card).delete()
        db.commit()

        bolt = Card(id="c1", name="Lightning Bolt", layout="normal", edhrec_rank=1, rarity="common", legalities={})
        shock = Card(id="c2", name="Shock", layout="normal", edhrec_rank=2, rarity="common", legalities={})
        growth = Card(id="c3", name="Giant Growth", layout="normal", edhrec_rank=3, rarity="common", legalities={})
        verbose_shock = Card(id="c4", name="Verbose Shock", layout="normal", edhrec_rank=4, rarity="common", legalities={})
        db.add_all([bolt, shock, growth, verbose_shock])
        db.flush()

        db.add_all(
            [
                CardFace(
                    card_id="c1",
                    name="Lightning Bolt",
                    type_line="Instant",
                    oracle_text="Lightning Bolt deals 3 damage to any target.",
                    colors=["R"],
                ),
                CardFace(
                    card_id="c2",
                    name="Shock",
                    type_line="Instant",
                    oracle_text="Shock deals 2 damage to any target.",
                    colors=["R"],
                ),
                CardFace(
                    card_id="c3",
                    name="Giant Growth",
                    type_line="Instant",
                    oracle_text="Target creature gets +3/+3 until end of turn.",
                    colors=["G"],
                ),
                CardFace(
                    card_id="c4",
                    name="Verbose Shock",
                    type_line="Instant",
                    oracle_text=(
                        "Shock deals 2 damage to any target.\n"
                        "Draw a card.\n"
                        "Then discard a card."
                    ),
                    colors=["R"],
                ),
            ]
        )
        db.commit()


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    _seed_db()
    with TestClient(app) as c:
        yield c


