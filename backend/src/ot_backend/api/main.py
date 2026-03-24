import importlib.metadata
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated, Final

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLTimeoutError
from sqlalchemy.orm import Session, joinedload

from ..core.config import SCHEMA_WAIT_INTERVAL_SECONDS, SCHEMA_WAIT_TIMEOUT_SECONDS
from ..core.database import get_db
from ..core.db_init import INIT_MODE_API, init_db, wait_for_migration_ready
from ..core.logging_config import log_performance, setup_loggers
from ..core.models import Card, CardFace

try:
    from ..embed.index import get_semantic_index
except ImportError:
    get_semantic_index = None

from .schemas import CardMatch, SimilarCard

setup_loggers()
logger = logging.getLogger("ot_backend.api")


def _get_api_version() -> str:
    try:
        return importlib.metadata.version("oracle-tutor-api")
    except importlib.metadata.PackageNotFoundError:
        return "1.2.0"


API_VERSION: Final[str] = _get_api_version()
_schema_ready: bool = False


def _ensure_schema_ready() -> None:
    global _schema_ready
    if _schema_ready:
        return
    if wait_for_migration_ready(timeout_s=0.0, interval_s=SCHEMA_WAIT_INTERVAL_SECONDS):
        _schema_ready = True
        return
    raise HTTPException(status_code=503, detail="Schema migration in progress. Please retry shortly.")


def _get_semantic_index():
    if get_semantic_index is None:
        return None
    return get_semantic_index()


def _to_similar_cards(results: list[tuple[tuple[str, int], float]], db: Session) -> list[SimilarCard]:
    if not results:
        return []

    from sqlalchemy import tuple_

    target_face_keys = [face_key for face_key, _ in results]
    key_to_score = {face_key: score for face_key, score in results}
    faces = (
        db.query(CardFace)
        .options(joinedload(CardFace.card))
        .filter(tuple_(CardFace.oracle_id, CardFace.face_ix).in_(target_face_keys))
        .all()
    )
    faces_map = {(face.oracle_id, face.face_ix): face for face in faces}

    similar_cards: list[SimilarCard] = []
    for face_key in target_face_keys:
        face = faces_map.get(face_key)
        if face is None:
            continue
        card = face.card
        similar_cards.append(
            SimilarCard(
                oracle_id=card.oracle_id,
                scryfall_id=card.scryfall_id,
                name=face.name,
                card_name=card.name,
                similarity=float(key_to_score.get(face_key, 0.0)),
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

    logger.info("Loading semantic model...")
    try:
        index = _get_semantic_index()
        if index is None:
            logger.warning("Semantic model not available — semantic endpoints will return 503")
        else:
            logger.info("Semantic model loaded and ready")
    except Exception as exc:
        logger.error("Semantic model failed to load: %s", exc, exc_info=True)

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
def search_cards(
    q: str,
    db: Session = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CardMatch]:
    _ensure_schema_ready()
    if not q.strip():
        return []
    cards = (
        db.query(Card)
        .filter(Card.name.ilike(f"%{q}%"))
        .order_by(Card.edhrec_rank.asc().nulls_last(), Card.name.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        CardMatch(
            name=c.name,
            oracle_id=c.oracle_id,
            scryfall_id=c.scryfall_id,
            rank=c.edhrec_rank,
        )
        for c in cards
    ]


@app.get("/card/{oracle_id}")
@log_performance(logger=logger)
def get_card_by_id(oracle_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    _ensure_schema_ready()
    card = db.query(Card).options(joinedload(Card.faces)).filter(Card.oracle_id == oracle_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card.to_dict()


@app.get("/similar-cards", response_model=list[SimilarCard])
@log_performance(logger=logger)
def get_similar_cards(
    db: Session = Depends(get_db),
    oracle_id: str | None = None,
    face_ix: Annotated[int, Query(ge=0)] = 0,
    q: str | None = None,
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
    if oracle_id is None and not (q and q.strip()):
        raise HTTPException(status_code=422, detail="Provide either oracle_id or q")

    index = _get_semantic_index()
    if index is None:
        raise HTTPException(status_code=503, detail="Semantic index not available")

    if oracle_id is not None:
        results = index.similar_to_face(
            (oracle_id, face_ix),
            limit=limit + offset,
            db=db,
            card_type=card_type,
            colors=colors,
            cmc_min=cmc_min,
            cmc_max=cmc_max,
            format=format,
            rarity=rarity,
            color_feature=color_feature,
        )
    else:
        assert q is not None  # guarded by the 422 check above
        results = index.search_oracle(
            q,
            limit=limit + offset,
            db=db,
            card_type=card_type,
            colors=colors,
            cmc_min=cmc_min,
            cmc_max=cmc_max,
            format=format,
            rarity=rarity,
            color_feature=color_feature,
        )

    return _to_similar_cards(results[offset:], db)
