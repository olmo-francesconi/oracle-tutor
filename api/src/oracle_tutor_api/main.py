from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.exc import OperationalError, TimeoutError as SQLTimeoutError
from sqlalchemy.orm import Session

from .data_builder import ensure_data_dir, update_scryfall_data
from .database import SessionLocal, get_db
from .db_init import init_db
from .logging_config import log_performance, setup_loggers
from .models import Card, CardFace, SystemMetadata
from .text_processing import expand_symbols
from .tfidf_index import TfidfIndex, build_tfidf_index

# Logging
setup_loggers()
logger = logging.getLogger("oracle_tutor_api.api")

# Global in-memory TF-IDF index (rebuilt on startup)
_tfidf_index: TfidfIndex | None = None
_tfidf_lock = threading.Lock()
_tfidf_data_version: str | None = None
_tfidf_last_version_check: float = 0.0  # time.monotonic()
_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    global _tfidf_index
    logger.info("API starting...")

    ensure_data_dir()
    try:
        init_db()
    except Exception as e:
        logger.error("DB init failed: %s", e, exc_info=True)

    def _get_db_data_version(db: Session) -> str | None:
        meta = db.get(SystemMetadata, "scryfall_data")
        if not meta:
            return None
        last_ing = ""
        try:
            last_ing = meta.last_ingestion.isoformat() if meta.last_ingestion else ""
        except Exception:
            last_ing = ""
        return f"{meta.schema_version or ''}|{meta.data_updated_at or ''}|{last_ing}"

    def rebuild_index() -> None:
        global _tfidf_index, _tfidf_data_version
        with _tfidf_lock:
            db = SessionLocal()
            try:
                _tfidf_index = build_tfidf_index(db)
                _tfidf_data_version = _get_db_data_version(db)
            finally:
                db.close()

    def run_update_and_rebuild() -> None:
        """
        Background task:
        - run stale-aware update (diff-ingest)
        - if ingestion ran, rebuild TF-IDF index
        """
        try:
            updated = update_scryfall_data(force=False)
            if updated:
                logger.info("Scryfall update completed; rebuilding TF-IDF index...")
                rebuild_index()
            else:
                logger.info("No Scryfall update needed.")
        except Exception as e:
            logger.error("Background update failed: %s", e, exc_info=True)

    # Initial TF-IDF build (best-effort; API can still start and lazily build later).
    try:
        rebuild_index()
    except Exception as e:
        logger.error("TF-IDF build failed (oracle search disabled until rebuild): %s", e, exc_info=True)
        _tfidf_index = None

    # Start scheduler inside API process.
    #
    # Railway best-practice: run scheduled ingestion in a separate worker service.
    # So in production we default this to disabled unless explicitly enabled.
    env = os.getenv("ORACLE_TUTOR_API_ENV", "development").lower()
    on_railway = any(
        os.getenv(k)
        for k in (
            "RAILWAY_ENVIRONMENT",
            "RAILWAY_PROJECT_ID",
            "RAILWAY_SERVICE_ID",
            "RAILWAY_PUBLIC_DOMAIN",
        )
    )
    default_update_enabled = "false" if (env in ("prod", "production") or on_railway) else "true"
    update_enabled = os.getenv("ORACLE_TUTOR_API_UPDATE_ENABLED", default_update_enabled).lower() in ("1", "true", "yes")
    if update_enabled:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger

            update_hour = int(os.getenv("ORACLE_TUTOR_API_UPDATE_HOUR", "2"))
            update_minute = int(os.getenv("ORACLE_TUTOR_API_UPDATE_MINUTE", "0"))
            every_days = int(os.getenv("ORACLE_TUTOR_API_UPDATE_EVERY_DAYS", "1"))
            every_days = max(1, every_days)

            _scheduler = BackgroundScheduler()
            _scheduler.add_job(
                run_update_and_rebuild,
                trigger=CronTrigger(hour=update_hour, minute=update_minute, day=f"*/{every_days}"),
                id="scryfall_update",
                name="Scryfall oracle bulk update",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            _scheduler.start()
            logger.info(
                "Scheduler started (every %d day(s) at %02d:%02d).",
                every_days,
                update_hour,
                update_minute,
            )
        except Exception as e:
            logger.error("Failed to start scheduler: %s", e, exc_info=True)
            _scheduler = None

        # Non-blocking startup staleness check/update.
        threading.Thread(target=run_update_and_rebuild, name="startup_update", daemon=True).start()
    else:
        logger.info("Scheduled updates disabled via ORACLE_TUTOR_API_UPDATE_ENABLED=false")

    yield

    # Shutdown
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped.")
        except Exception as e:
            logger.warning("Scheduler shutdown failed: %s", e, exc_info=True)
        finally:
            _scheduler = None


app = FastAPI(lifespan=lifespan, title="oracle-tutor api")


# ---- Exception Handlers ----

@app.exception_handler(SQLTimeoutError)
@app.exception_handler(OperationalError)
async def database_connection_exception_handler(request: Request, exc: Exception):
    """
    Handle database connection pool exhaustion and other database connection errors gracefully.
    Returns 503 Service Unavailable instead of crashing.
    """
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


# CORS:
# - For Railway + same-origin (recommended): do NOT enable CORS.
# - If you truly need cross-origin access, set ORACLE_TUTOR_API_CORS_ORIGINS to a
#   comma-separated list (e.g. "https://example.com,https://www.example.com").
cors_origins_env = os.getenv("ORACLE_TUTOR_API_CORS_ORIGINS", "").strip()
if cors_origins_env:
    origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,  # public API; avoid CSRF footguns
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ---- Pydantic models ----

class CardMatch(BaseModel):
    name: str
    similarity: float = 1.0
    rank: Optional[int] = None
    id: Optional[str] = None


class CardNameMatch(BaseModel):
    name: str
    id: str


class SimilarCard(BaseModel):
    id: str  # Card id
    name: str  # Face name
    card_name: str  # Full Card name
    similarity: float
    rank: Optional[int] = None

    type_line: Optional[str] = None
    mana_cost: Optional[str] = None
    oracle_text: Optional[str] = None
    power: Optional[str] = None
    toughness: Optional[str] = None
    colors: Optional[List[str]] = None

    layout: Optional[str] = None
    rarity: Optional[str] = None
    legalities: Optional[Dict[str, str]] = None


# ---- Meta ----

@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {"service": "oracle-tutor-api"}


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


def _require_index() -> TfidfIndex:
    """
    Ensure the global TF-IDF index is present and (eventually) consistent with DB updates.

    The worker updates `system_metadata(key='scryfall_data')` when ingestion completes.
    We poll that row (throttled) and rebuild this in-memory index when it changes.
    """
    global _tfidf_index, _tfidf_data_version, _tfidf_last_version_check

    check_every_s = float(os.getenv("ORACLE_TUTOR_API_INDEX_VERSION_CHECK_SECONDS", "30"))
    now = time.monotonic()
    should_check = (_tfidf_index is None) or ((now - _tfidf_last_version_check) >= check_every_s)

    if should_check:
        # Lazy-build so the API can still function if DB wasn't ready at startup,
        # and so tests can seed data before first oracle query.
        try:
            with _tfidf_lock:
                # Recompute under lock to avoid stampede.
                now2 = time.monotonic()
                should_check2 = (_tfidf_index is None) or ((now2 - _tfidf_last_version_check) >= check_every_s)
                if should_check2:
                    _tfidf_last_version_check = now2
                    db = SessionLocal()
                    try:
                        meta = db.get(SystemMetadata, "scryfall_data")
                        db_version: str | None = None
                        if meta:
                            last_ing = ""
                            try:
                                last_ing = meta.last_ingestion.isoformat() if meta.last_ingestion else ""
                            except Exception:
                                last_ing = ""
                            db_version = f"{meta.schema_version or ''}|{meta.data_updated_at or ''}|{last_ing}"

                        if _tfidf_index is None:
                            _tfidf_index = build_tfidf_index(db)
                            _tfidf_data_version = db_version
                        else:
                            if db_version and (_tfidf_data_version is None or db_version != _tfidf_data_version):
                                logger.info("DB data version changed; rebuilding TF-IDF index...")
                                _tfidf_index = build_tfidf_index(db)
                                _tfidf_data_version = db_version
                    finally:
                        db.close()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"TF-IDF index not loaded yet: {e}") from e

    # mypy/pydantic: at this point we should have an index unless build failed
    if _tfidf_index is None:
        raise HTTPException(status_code=503, detail="TF-IDF index not loaded yet.")
    return _tfidf_index


# ---- Endpoints ----

@app.get("/search", response_model=List[CardMatch])
@log_performance(logger=logger)
def search_cards(q: str, limit: int = 5, db: Session = Depends(get_db)):
    if not q.strip():
        return []
    limit = max(1, min(limit, 25))

    if db.bind and db.bind.dialect.name == "postgresql":
        distance = Card.name.op("<->")(q)
        results = (
            db.query(Card, distance.label("dist"))
            .filter(or_(Card.name.op("%")(q), Card.name.ilike(f"%{q}%")))
            .order_by(distance, Card.edhrec_rank.asc().nulls_last())
            .limit(limit)
            .all()
        )
        return [
            CardMatch(name=c.name, id=c.id, rank=c.edhrec_rank, similarity=float(1.0 - dist))
            for c, dist in results
        ]

    # Non-Postgres fallback (tests): basic contains.
    cards = (
        db.query(Card)
        .filter(Card.name.ilike(f"%{q}%"))
        .order_by(Card.edhrec_rank.asc().nulls_last(), Card.name.asc())
        .limit(limit)
        .all()
    )
    return [CardMatch(name=c.name, id=c.id, rank=c.edhrec_rank, similarity=1.0) for c in cards]


@app.get("/suggest-names", response_model=List[CardNameMatch])
@log_performance(logger=logger)
def search_card_names(q: str, limit: int = 5, db: Session = Depends(get_db)):
    if not q.strip():
        return []
    limit = max(1, min(limit, 25))

    if db.bind and db.bind.dialect.name == "postgresql":
        distance = Card.name.op("<->")(q)
        cards = (
            db.query(Card.name, Card.id)
            .filter(or_(Card.name.op("%")(q), Card.name.ilike(f"%{q}%")))
            .order_by(distance, Card.edhrec_rank.asc().nulls_last())
            .limit(limit)
            .all()
        )
        return [CardNameMatch(name=c.name, id=c.id) for c in cards]

    cards = (
        db.query(Card.name, Card.id)
        .filter(Card.name.ilike(f"%{q}%"))
        .order_by(Card.name.asc())
        .limit(limit)
        .all()
    )
    return [CardNameMatch(name=c.name, id=c.id) for c in cards]


@app.get("/card/{card_id}")
@log_performance(logger=logger)
def get_card_by_id(card_id: str, db: Session = Depends(get_db)):
    card = db.get(Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    # Ensure faces are loaded (relationship might be lazy)
    _ = card.faces
    return card.to_dict()


@app.get("/similar-cards/{card_id}", response_model=List[SimilarCard])
@log_performance(logger=logger)
def get_similar_cards(
    card_id: str,
    face_index: int = 0,
    limit: int = 20,
    offset: int = 0,
    card_type: Optional[str] = Query(None),
    colors: Optional[str] = Query(None),
    format: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    index = _require_index()

    target_card = db.get(Card, card_id)
    if not target_card:
        raise HTTPException(status_code=404, detail="Card not found")

    faces = (
        db.query(CardFace)
        .filter(CardFace.card_id == target_card.id)
        .order_by(CardFace.id.asc())
        .all()
    )
    if not faces:
        raise HTTPException(status_code=404, detail="Card has no faces data")
    if face_index < 0 or face_index >= len(faces):
        raise HTTPException(status_code=400, detail="Invalid face_index")

    seed_face = faces[face_index]
    results = index.similar(
        seed_face_id=seed_face.id,
        exclude_card_id=target_card.id,
        limit=max(1, min(limit, 100)),
        offset=max(0, offset),
        card_type=card_type,
        colors=colors,
        format=format,
    )
    if not results:
        return []

    target_face_ids = [r[0] for r in results]
    id_to_score = {r[0]: r[1] for r in results}

    cards_data = (
        db.query(CardFace, Card)
        .join(Card, CardFace.card_id == Card.id)
        .filter(CardFace.id.in_(target_face_ids))
        .all()
    )
    cards_map = {face.id: (face, card) for face, card in cards_data}

    out: List[SimilarCard] = []
    for face_id in target_face_ids:
        if face_id not in cards_map:
            continue
        face, card = cards_map[face_id]
        sim = float(id_to_score.get(face_id, 0.0))
        out.append(
            SimilarCard(
                id=card.id,
                name=face.name,
                card_name=card.name,
                similarity=sim,
                rank=card.edhrec_rank,
                type_line=face.type_line,
                mana_cost=face.mana_cost,
                oracle_text=face.oracle_text,
                power=face.power,
                toughness=face.toughness,
                layout=card.layout,
                rarity=card.rarity,
                colors=face.colors,
                legalities=card.legalities,
            )
        )
    return out


@app.get("/search-oracle", response_model=List[SimilarCard])
@log_performance(logger=logger)
def search_oracle_text(
    q: str,
    limit: int = 20,
    offset: int = 0,
    card_type: Optional[str] = Query(None),
    colors: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    if not q.strip():
        return []

    index = _require_index()

    # Expand symbol syntax & strip reminder punctuation in query (helps tokenization).
    expanded_query = expand_symbols(q)
    if not expanded_query.strip():
        return []

    results = index.search(
        query=expanded_query,
        limit=max(1, min(limit, 100)),
        offset=max(0, offset),
        card_type=card_type,
        colors=colors,
    )
    if not results:
        return []

    target_face_ids = [r[0] for r in results]
    id_to_score = {r[0]: r[1] for r in results}

    cards_data = (
        db.query(CardFace, Card)
        .join(Card, CardFace.card_id == Card.id)
        .filter(CardFace.id.in_(target_face_ids))
        .all()
    )
    cards_map = {face.id: (face, card) for face, card in cards_data}

    out: List[SimilarCard] = []
    for face_id in target_face_ids:
        if face_id not in cards_map:
            continue
        face, card = cards_map[face_id]
        sim = float(id_to_score.get(face_id, 0.0))
        out.append(
            SimilarCard(
                id=card.id,
                name=face.name,
                card_name=card.name,
                similarity=sim,
                rank=card.edhrec_rank,
                type_line=face.type_line,
                mana_cost=face.mana_cost,
                oracle_text=face.oracle_text,
                power=face.power,
                toughness=face.toughness,
                layout=card.layout,
                rarity=card.rarity,
                colors=face.colors,
                legalities=card.legalities,
            )
        )
    return out


