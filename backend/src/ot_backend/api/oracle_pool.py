from __future__ import annotations

import asyncio
import logging
import os

from fastapi import FastAPI
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.database import SessionLocal
from ..core.models import CardFace, CardRaw
from .routers.search import (
    HOME_TERM_POOL_LIMIT,
    ORACLE_TEXT_POOL_LIMIT,
    build_home_term_pool,
)

logger = logging.getLogger("ot_backend.api")


def _oracle_pool_refresh_seconds() -> float:
    return float(os.getenv("OT_ORACLE_POOL_REFRESH_SECONDS", "600"))


def _sample_oracle_texts(db: Session) -> list[tuple[str | None]]:
    rows = (
        db.query(CardFace.oracle_text)
        .filter(CardFace.oracle_text.isnot(None), CardFace.oracle_text != "")
        .order_by(func.random())
        .limit(ORACLE_TEXT_POOL_LIMIT)
        .all()
    )
    return [(row[0],) for row in rows]


def _sample_keywords(db: Session) -> list[tuple[list[str] | None]]:
    rows = (
        db.query(CardRaw.keywords)
        .filter(CardRaw.keywords.isnot(None))
        .order_by(func.random())
        .limit(HOME_TERM_POOL_LIMIT)
        .all()
    )
    return [(row[0],) for row in rows]


def load_oracle_pools() -> tuple[list[str], list[str]]:
    """Fetch fresh oracle-text and home-term pools from the DB. Blocking."""
    with SessionLocal() as db:
        oracle_rows = _sample_oracle_texts(db)
        keyword_rows = _sample_keywords(db)

    oracle_text_pool = [row[0] for row in oracle_rows if row[0] and row[0].strip()]
    home_term_pool = build_home_term_pool(keyword_rows, oracle_rows)
    return oracle_text_pool, home_term_pool


def apply_oracle_pools(app: FastAPI, oracle_text_pool: list[str], home_term_pool: list[str]) -> None:
    app.state.oracle_text_pool = oracle_text_pool
    app.state.home_term_pool = home_term_pool


async def rotate_oracle_pools(app: FastAPI) -> None:
    """Periodic background refresh. Swallows per-iteration errors so a transient
    DB hiccup doesn't kill the rotation loop."""
    interval = _oracle_pool_refresh_seconds()
    while True:
        try:
            await asyncio.sleep(interval)
            oracle_text_pool, home_term_pool = await asyncio.to_thread(load_oracle_pools)
            apply_oracle_pools(app, oracle_text_pool, home_term_pool)
            logger.info(
                "Oracle home pools rotated: %d texts, %d terms",
                len(oracle_text_pool),
                len(home_term_pool),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Oracle home pools rotation failed (non-fatal): %s", exc)
