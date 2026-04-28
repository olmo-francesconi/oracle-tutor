import atexit
import os
import sys
from collections.abc import Generator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer

# ---------------------------------------------------------------------------
# Session-wide Postgres container
#
# Tests run against a real Postgres (with pgvector) rather than SQLite so the
# app exercises the same code paths as production — pgvector queries, JSONB,
# ARRAY columns, GIN indexes, advisory locks, FOR UPDATE SKIP LOCKED, etc.
# The container starts once per session, survives across tests via the
# per-test truncate+seed pattern in _seed_db, and is torn down at exit.
# ---------------------------------------------------------------------------

_POSTGRES_IMAGE = "pgvector/pgvector:pg17"

_container = PostgresContainer(_POSTGRES_IMAGE, driver="psycopg")
_container.start()
atexit.register(_container.stop)

# testcontainers returns a SQLAlchemy-ready URL with the psycopg driver.
_database_url = _container.get_connection_url()

# pgvector requires the `vector` extension; create it before the app imports
# the engine so migrations can refer to it.
with psycopg.connect(_database_url.replace("+psycopg", "")) as _setup_conn:
    with _setup_conn.cursor() as _cur:
        _cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    _setup_conn.commit()

os.environ["DATABASE_URL"] = _database_url
os.environ.setdefault("OT_UPDATE_ENABLED", "false")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("ADMIN_JWT_SECRET", "test-admin-jwt-secret-which-is-at-least-32-bytes")
# Prevent lifespan's wait_for_migration_ready from blocking for 30s if state is stale.
os.environ.setdefault("OT_SCHEMA_WAIT_TIMEOUT_SECONDS", "0.5")

# Ensure the `src/` layout package is importable when running pytest without an editable install.
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from ot_backend.api.admin_auth import clear_admin_login_attempts_for_tests  # noqa: E402
from ot_backend.api.main import app  # noqa: E402
from ot_backend.core.database import SessionLocal  # noqa: E402
from ot_backend.core.db_init import init_db  # noqa: E402
from ot_backend.core.models import (  # noqa: E402
    Card,
    CardFace,
    CardRaw,
    SemanticJob,
    SemanticModel,
    SemanticModelArtifact,
    SemanticModelEmbedding,
    SystemMetadata,
)


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
        db.query(SemanticJob).delete()
        db.query(SemanticModelEmbedding).delete()
        db.query(SemanticModelArtifact).delete()
        db.query(SemanticModel).delete()
        db.query(CardFace).delete()
        db.query(Card).delete()
        db.query(CardRaw).delete()
        db.query(SystemMetadata).delete()
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


@pytest.fixture(autouse=True)
def reset_admin_login_attempt_state() -> Generator[None, None, None]:
    clear_admin_login_attempts_for_tests()
    yield
    clear_admin_login_attempts_for_tests()


@pytest.fixture(autouse=True)
def _reset_module_globals() -> Generator[None, None, None]:
    """Reset leaked module-level state between tests."""
    yield
    # Semantic index cache — prevents stale model references across tests
    from ot_backend.semantic import index as _idx
    _idx._index = None
    _idx._last_refresh_check = 0.0
    _idx._loaded_model_id = _idx._UNSET

    # Schema-ready flag — must re-check after each test's DB mutations
    from ot_backend.api import _ensure_schema_ready as _esr
    _esr._schema_ready = False
