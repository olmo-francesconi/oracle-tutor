from __future__ import annotations

import importlib.metadata
import logging
import os
import random
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Final, Literal, Protocol, cast

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLTimeoutError
from sqlalchemy.orm import Session, joinedload

from ..core.config import SCHEMA_WAIT_INTERVAL_SECONDS, SCHEMA_WAIT_TIMEOUT_SECONDS
from ..core.database import get_db
from ..core.db_init import INIT_MODE_API, init_db, wait_for_migration_ready
from ..core.logging_config import log_performance, setup_loggers
from ..core.models import Card, CardFace, CardRaw

try:
    from ..embed.index import get_semantic_index
except ImportError:
    get_semantic_index = None

from .schemas import CardMatch, OracleSamplesResponse, SimilarCard, SimilarCardsPage

logger = logging.getLogger("ot_backend.api")


class SemanticIndexProtocol(Protocol):
    def similar_to_face(
        self,
        face_key: tuple[str, int],
        limit: int,
        db: Session,
        card_type: str | None = None,
        colors: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        format: str | None = None,
        rarity: list[str] | None = None,
        color_feature: str = "identity",
        match_mode: str = "at_least",
    ) -> list[tuple[tuple[str, int], float]]: ...

    def search_oracle(
        self,
        query: str,
        limit: int,
        db: Session,
        card_type: str | None = None,
        colors: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        format: str | None = None,
        rarity: list[str] | None = None,
        color_feature: str = "identity",
        match_mode: str = "at_least",
    ) -> list[tuple[tuple[str, int], float]]: ...


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def _get_api_version() -> str:
    try:
        return importlib.metadata.version("oracle-tutor-api")
    except importlib.metadata.PackageNotFoundError:
        return "1.2.0"


API_VERSION: Final[str] = _get_api_version()
MAX_SEARCH_LIMIT: Final[int] = 25
MAX_SIMILAR_CARDS_LIMIT: Final[int] = 100

DOUBLE_SIDED_LAYOUTS: Final[frozenset[str]] = frozenset(
    {
        "transform",
        "modal_dfc",
        "meld",
        "double_faced_token",
        "art_series",
    }
)
_RARITY_MAP: Final = {"c": "common", "u": "uncommon", "r": "rare", "m": "mythic"}
ORACLE_TEXT_POOL_LIMIT: Final[int] = 300
HOME_TERM_POOL_LIMIT: Final[int] = 300
ABILITY_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*([A-Za-z][A-Za-z' -]{1,40}?)\s+[—-]\s+", re.MULTILINE)
_schema_ready: bool = False
_oracle_text_pool: list[str] = []
_home_term_pool: list[str] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_schema_ready() -> None:
    global _schema_ready
    if _schema_ready:
        return
    if wait_for_migration_ready(timeout_s=0.0, interval_s=SCHEMA_WAIT_INTERVAL_SECONDS):
        _schema_ready = True
        return
    raise HTTPException(status_code=503, detail="Schema migration in progress. Please retry shortly.")


def _get_semantic_index() -> SemanticIndexProtocol | None:
    if get_semantic_index is None:
        return None
    return cast(Callable[[], SemanticIndexProtocol | None], get_semantic_index)()


def _image_side_for_face(layout: str | None, face_ix: int) -> Literal["front", "back"]:
    if layout in DOUBLE_SIDED_LAYOUTS and face_ix > 0:
        return "back"
    return "front"


def _normalize_home_term(term: str) -> str:
    return " ".join(term.split()).strip(" -\u2014")


def _extract_ability_words(text: str | None) -> list[str]:
    if not text or not text.strip():
        return []
    return [_normalize_home_term(match.group(1)) for match in ABILITY_WORD_PATTERN.finditer(text)]


def _build_home_term_pool(keyword_rows: list[tuple[list[str] | None]], oracle_rows: list[tuple[str | None]]) -> list[str]:
    deduped_terms: dict[str, str] = {}

    for keywords, in keyword_rows:
        for keyword in keywords or []:
            normalized = _normalize_home_term(keyword)
            if normalized:
                deduped_terms.setdefault(normalized.casefold(), normalized)

    for oracle_text, in oracle_rows:
        for ability_word in _extract_ability_words(oracle_text):
            if ability_word:
                deduped_terms.setdefault(ability_word.casefold(), ability_word)

    return list(deduped_terms.values())


def _to_similar_cards(results: list[tuple[tuple[str, int], float]], db: Session) -> list[SimilarCard]:
    if not results:
        return []

    from sqlalchemy import tuple_

    target_face_keys = [face_key for face_key, _ in results]
    key_to_score = {face_key: score for face_key, score in results}
    faces = (
        db.query(CardFace)
        .options(joinedload(CardFace.card).joinedload(Card.raw_printing))
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
                face_ix=face.face_ix,
                image_side=_image_side_for_face(card.layout, face.face_ix),
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
                border_color=card.raw_printing.border_color,
                set_code=card.raw_printing.set_code,
            )
        )
    return similar_cards


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    setup_loggers()
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

    from ..core.config import semantic_model_path, semantic_onnx_model_path

    model_root = semantic_model_path()
    onnx_path = semantic_onnx_model_path()
    logger.info("Loading semantic model... (model_root=%s, onnx=%s)", model_root, onnx_path)
    if not model_root.exists():
        logger.warning("Semantic model root not found: %s", model_root)
    elif not onnx_path.exists():
        logger.warning("ONNX artifact not found: %s", onnx_path)
    try:
        index = _get_semantic_index()
        if index is None:
            logger.warning("Semantic model unavailable — semantic endpoints will return 503")
        else:
            logger.info("Semantic model loaded and ready")
    except Exception as exc:
        logger.error("Semantic model failed to load: %s", exc, exc_info=True)

    global _home_term_pool, _oracle_text_pool
    try:
        db = next(get_db())
        try:
            oracle_rows = (
                db.query(CardFace.oracle_text)
                .filter(
                    CardFace.oracle_text.isnot(None),
                    CardFace.oracle_text != "",
                )
                .order_by(func.random())
                .limit(ORACLE_TEXT_POOL_LIMIT)
                .all()
            )
            _oracle_text_pool.extend(
                row[0] for row in oracle_rows if row[0] and row[0].strip()
            )
            keyword_rows = (
                db.query(CardRaw.keywords)
                .filter(CardRaw.keywords.isnot(None))
                .order_by(func.random())
                .limit(HOME_TERM_POOL_LIMIT)
                .all()
            )
            _home_term_pool.extend(_build_home_term_pool(keyword_rows, oracle_rows))
            logger.info("Oracle home pools loaded: %d texts, %d terms", len(_oracle_text_pool), len(_home_term_pool))
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Oracle home pools failed to load: %s", exc)

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


# ---------------------------------------------------------------------------
# Routes — meta
# ---------------------------------------------------------------------------


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
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/oracle-samples", response_model=OracleSamplesResponse, tags=["meta"])
def oracle_samples(
    n: int = Query(60, ge=1, le=100),
) -> OracleSamplesResponse:
    texts = random.sample(_oracle_text_pool, min(n, len(_oracle_text_pool))) if _oracle_text_pool else []
    terms = random.sample(_home_term_pool, min(n, len(_home_term_pool))) if _home_term_pool else []
    return OracleSamplesResponse(texts=texts, terms=terms)


# ---------------------------------------------------------------------------
# Routes — search
# ---------------------------------------------------------------------------


@app.get("/search", response_model=list[CardMatch])
@log_performance(logger=logger)
def search_cards(
    q: str,
    db: Session = Depends(get_db),
    limit: int = Query(10, ge=1, le=MAX_SEARCH_LIMIT),
    offset: int = Query(0, ge=0),
) -> list[CardMatch]:
    _ensure_schema_ready()
    if not q.strip():
        return []

    q_like = f"%{q}%"
    faces = (
        db.query(CardFace)
        .join(Card, Card.oracle_id == CardFace.oracle_id)
        .filter((CardFace.name.ilike(q_like)) | (Card.name.ilike(q_like)))
        .order_by(Card.edhrec_rank.asc().nulls_last(), Card.name.asc(), CardFace.face_ix.asc(), CardFace.name.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        CardMatch(
            name=face.name,
            oracle_id=face.card.oracle_id,
            scryfall_id=face.card.scryfall_id,
            face_ix=face.face_ix,
            image_side=_image_side_for_face(face.card.layout, face.face_ix),
            rank=face.card.edhrec_rank,
        )
        for face in faces
    ]


@app.get("/card/{oracle_id}")
@log_performance(logger=logger)
def get_card_by_id(oracle_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    _ensure_schema_ready()
    card = db.query(Card).options(joinedload(Card.faces)).filter(Card.oracle_id == oracle_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card.to_dict()


def _parse_rarity(rarity: str | None) -> list[str] | None:
    if rarity is None:
        return None
    chars = list(rarity.lower())
    invalid = [ch for ch in chars if ch not in _RARITY_MAP]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid rarity characters: {', '.join(invalid)!r}. Use c, u, r, m.",
        )
    if len(chars) != len(set(chars)):
        raise HTTPException(status_code=422, detail="Duplicate rarity characters in rarity filter")
    return [_RARITY_MAP[ch] for ch in chars]


@app.get("/similar-cards", response_model=SimilarCardsPage)
@log_performance(logger=logger)
def get_similar_cards(
    db: Session = Depends(get_db),
    oracle_id: str | None = None,
    face_ix: int = Query(0, ge=0),
    q: str | None = None,
    limit: int = Query(20, ge=1, le=MAX_SIMILAR_CARDS_LIMIT),
    offset: int = Query(0, ge=0),
    card_type: str | None = None,
    colors: str | None = None,
    cmc_min: float | None = None,
    cmc_max: float | None = None,
    format: str | None = None,
    rarity: str | None = None,
    color_feature: str = "identity",
    match_mode: str = "at_least",
) -> SimilarCardsPage:
    _ensure_schema_ready()
    if oracle_id is None and not (q and q.strip()):
        raise HTTPException(status_code=422, detail="Provide either oracle_id or q")

    rarity_list = _parse_rarity(rarity)

    index = _get_semantic_index()
    if index is None:
        raise HTTPException(status_code=503, detail="Semantic index not available")

    if oracle_id is not None:
        results = index.similar_to_face(
            (oracle_id, face_ix),
            limit=limit + offset + 1,
            db=db,
            card_type=card_type,
            colors=colors,
            cmc_min=cmc_min,
            cmc_max=cmc_max,
            format=format,
            rarity=rarity_list,
            color_feature=color_feature,
            match_mode=match_mode,
        )
    else:
        assert q is not None  # guarded by the 422 check above
        results = index.search_oracle(
            q,
            limit=limit + offset + 1,
            db=db,
            card_type=card_type,
            colors=colors,
            cmc_min=cmc_min,
            cmc_max=cmc_max,
            format=format,
            rarity=rarity_list,
            color_feature=color_feature,
            match_mode=match_mode,
        )

    page_results = results[offset : offset + limit]
    has_more = len(results) > offset + limit
    return SimilarCardsPage(items=_to_similar_cards(page_results, db), has_more=has_more)
