from __future__ import annotations

import importlib.metadata
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated, Final

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLTimeoutError
from sqlalchemy.orm import Session

from ..core.config import SCHEMA_WAIT_INTERVAL_SECONDS, SCHEMA_WAIT_TIMEOUT_SECONDS
from ..core.database import get_db
from ..core.db_init import INIT_MODE_API, init_db, wait_for_migration_ready
from ..core.logging_config import log_performance, setup_loggers
from ..core.models import Card, CardFace
from .schemas import CardMatch, CardNameMatch, SimilarCard

try:
    from ..semantic.index import get_semantic_index
except ImportError:
    get_semantic_index = None

setup_loggers()
logger = logging.getLogger("ot_backend.api")
DbSession = Annotated[Session, Depends(get_db)]


def _get_api_version() -> str:
    try:
        return importlib.metadata.version("oracle-tutor-api")
    except importlib.metadata.PackageNotFoundError:
        return "1.2.0"


API_VERSION: Final[str] = _get_api_version()


def _ensure_schema_ready() -> None:
    if wait_for_migration_ready(timeout_s=0.0, interval_s=SCHEMA_WAIT_INTERVAL_SECONDS):
        return
    raise HTTPException(status_code=503, detail="Schema migration in progress. Please retry shortly.")


def _is_postgres(db: Session) -> bool:
    return bool(db.bind and db.bind.dialect.name == "postgresql")


def _get_semantic_index():
    if get_semantic_index is None:
        return None
    return get_semantic_index()


def _to_similar_cards(results: list[tuple[int, float]], db: Session) -> list[SimilarCard]:
    if not results:
        return []

    target_face_ids = [face_id for face_id, _ in results]
    id_to_score = {face_id: score for face_id, score in results}
    faces = db.query(CardFace).filter(CardFace.id.in_(target_face_ids)).all()
    faces_map = {face.id: face for face in faces}

    similar_cards: list[SimilarCard] = []
    for face_id in target_face_ids:
        face = faces_map.get(face_id)
        if face is None:
            continue
        card = face.card
        similar_cards.append(
            SimilarCard(
                id=card.id,
                name=face.name,
                card_name=card.name,
                similarity=float(id_to_score.get(face_id, 0.0)),
                rank=card.edhrec_rank,
                type_line=face.type_line,
                mana_cost=face.mana_cost,
                oracle_text=face.oracle_text,
                power=face.power,
                toughness=face.toughness,
                colors=face.colors,
                layout=card.layout,
                rarity=card.rarity,
                legalities=card.legalities,
                uniqueness=card.uniqueness,
            )
        )
    return similar_cards


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("API starting...")

    try:
        init_db(mode=INIT_MODE_API)
        if not wait_for_migration_ready(
            timeout_s=SCHEMA_WAIT_TIMEOUT_SECONDS,
            interval_s=SCHEMA_WAIT_INTERVAL_SECONDS,
        ):
            logger.warning(
                "Schema migration is not ready after %.1fs; API data endpoints will return 503 until ready.",
                SCHEMA_WAIT_TIMEOUT_SECONDS,
            )
    except Exception as exc:
        logger.error("DB init failed: %s", exc, exc_info=True)

    yield

    logger.info("API shutting down...")


app = FastAPI(lifespan=lifespan, title="oracle-tutor api", version=API_VERSION)


@app.exception_handler(SQLTimeoutError)
@app.exception_handler(OperationalError)
async def database_connection_exception_handler(request: Request, exc: Exception):
    logger.warning(
        "Database connection error on %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": "Service temporarily unavailable due to high load. Please try again in a moment.",
            "error": "database_connection_error",
        },
    )


cors_origins_env = os.getenv("ORACLE_TUTOR_API_CORS_ORIGINS", "").strip()
if cors_origins_env:
    origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {"service": "oracle-tutor-api"}


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version", tags=["meta"])
def version() -> dict[str, str]:
    return {"version": API_VERSION}


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/search", response_model=list[CardMatch])
@log_performance(logger=logger)
def search_cards(q: str, db: DbSession, limit: int = 5) -> list[CardMatch]:
    _ensure_schema_ready()
    if not q.strip():
        return []
    limit = max(1, min(limit, 25))

    if _is_postgres(db):
        distance = Card.name.op("<->")(q)
        results = (
            db.query(Card, distance.label("dist"))
            .filter(or_(Card.name.op("%")(q), Card.name.ilike(f"%{q}%")))
            .order_by(distance, Card.edhrec_rank.asc().nulls_last())
            .limit(limit)
            .all()
        )
        return [
            CardMatch(name=card.name, id=card.id, rank=card.edhrec_rank, similarity=float(1.0 - dist))
            for card, dist in results
        ]

    cards = (
        db.query(Card)
        .filter(Card.name.ilike(f"%{q}%"))
        .order_by(Card.edhrec_rank.asc().nulls_last(), Card.name.asc())
        .limit(limit)
        .all()
    )
    return [CardMatch(name=card.name, id=card.id, rank=card.edhrec_rank, similarity=1.0) for card in cards]


@app.get("/suggest-names", response_model=list[CardNameMatch])
@log_performance(logger=logger)
def search_card_names(q: str, db: DbSession, limit: int = 5, offset: int = 0) -> list[CardNameMatch]:
    _ensure_schema_ready()
    if not q.strip():
        return []
    limit = max(1, min(limit, 25))
    offset = max(0, offset)

    if _is_postgres(db):
        distance = Card.name.op("<->")(q)
        cards = (
            db.query(Card.name, Card.id)
            .filter(or_(Card.name.op("%")(q), Card.name.ilike(f"%{q}%")))
            .order_by(distance, Card.edhrec_rank.asc().nulls_last())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [CardNameMatch(name=name, id=card_id) for name, card_id in cards]

    cards = (
        db.query(Card.name, Card.id)
        .filter(Card.name.ilike(f"%{q}%"))
        .order_by(Card.name.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [CardNameMatch(name=name, id=card_id) for name, card_id in cards]


@app.get("/card/{card_id}")
@log_performance(logger=logger)
def get_card_by_id(card_id: str, db: DbSession) -> dict[str, object]:
    _ensure_schema_ready()
    card = db.get(Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    _ = card.faces
    return card.to_dict()


@app.get("/similar-cards/{card_id}", response_model=list[SimilarCard])
@log_performance(logger=logger)
def get_similar_cards(
    card_id: str,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    card_type: str | None = None,
    colors: str | None = None,
    cmc_min: float | None = None,
    cmc_max: float | None = None,
    format: str | None = None,
    rarity: str | None = None,
    color_feature: str = "identity",
) -> list[SimilarCard]:
    _ensure_schema_ready()
    index = _get_semantic_index()
    if index is None:
        raise HTTPException(status_code=503, detail="Semantic index not available")

    _ = (card_type, colors, cmc_min, cmc_max, format, rarity, color_feature)

    face = db.query(CardFace).filter(CardFace.card_id == card_id).order_by(CardFace.id.asc()).first()
    if face is None:
        raise HTTPException(status_code=404, detail="Card not found")

    results = index.similar_to_face(face.id, limit=limit + offset, db=db)
    return _to_similar_cards(results[offset:], db)


@app.get("/search-oracle", response_model=list[SimilarCard])
@log_performance(logger=logger)
def search_oracle_text(
    q: str,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    card_type: str | None = None,
    colors: str | None = None,
    cmc_min: float | None = None,
    cmc_max: float | None = None,
    format: str | None = None,
    rarity: str | None = None,
    color_feature: str = "identity",
) -> list[SimilarCard]:
    _ensure_schema_ready()
    if not q.strip():
        return []

    index = _get_semantic_index()
    if index is None:
        raise HTTPException(status_code=503, detail="Semantic index not available")

    _ = (card_type, colors, cmc_min, cmc_max, format, rarity, color_feature)

    results = index.search_oracle(q, limit=limit + offset, db=db)
    return _to_similar_cards(results[offset:], db)
