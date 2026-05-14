from __future__ import annotations

import logging
import random
import re
import time
from typing import Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, func, tuple_
from sqlalchemy.orm import Session, joinedload

from ...core.config import MAX_QUERY_LENGTH
from ...core.database import get_db
from ...core.logging_config import log_performance
from ...core.models import Card, CardFace, SemanticQueryLog
from .. import _semantic_index as _sem_idx_mod
from .._ensure_schema_ready import ensure_schema_ready
from ..schemas import CardMatch, OracleSamplesResponse, SimilarCard, SimilarCardsPage

logger = logging.getLogger("ot_backend.api")

router = APIRouter(tags=["search"])

MAX_SEARCH_LIMIT: Final[int] = 25
MAX_SIMILAR_CARDS_LIMIT: Final[int] = 100
ORACLE_TEXT_POOL_LIMIT: Final[int] = 300
HOME_TERM_POOL_LIMIT: Final[int] = 300
ABILITY_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*([A-Za-z][A-Za-z' -]{1,40}?)\s+[—-]\s+", re.MULTILINE)

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
_CARD_TYPE_MAP: Final = {
    "c": "creature",
    "i": "instant",
    "s": "sorcery",
    "e": "enchantment",
    "a": "artifact",
    "p": "planeswalker",
    "l": "land",
}
_FORMAT_MAP: Final = {
    "s": "standard",
    "p": "pioneer",
    "m": "modern",
    "l": "legacy",
    "v": "vintage",
    "c": "commander",
    "u": "pauper",
}


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


def build_home_term_pool(keyword_rows: list[tuple[list[str] | None]], oracle_rows: list[tuple[str | None]]) -> list[str]:
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


def _parse_code_filter(raw_value: str | None, value_map: dict[str, str], field_name: str) -> list[str] | None:
    if raw_value is None:
        return None

    codes = [value for value in raw_value.strip().lower() if value]
    if not codes:
        return None

    invalid = [code for code in codes if code not in value_map]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid {field_name} codes: {', '.join(invalid)}")
    if len(codes) != len(set(codes)):
        raise HTTPException(status_code=422, detail=f"Duplicate {field_name} codes in filter")

    return [value_map[code] for code in codes]


def _to_similar_cards(results: list[tuple[tuple[str, int], float]], db: Session) -> list[SimilarCard]:
    if not results:
        return []

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
                border_color=card.raw_printing.border_color,
                set_code=card.raw_printing.set_code,
            )
        )
    return similar_cards


@router.get("/oracle-samples", response_model=OracleSamplesResponse)
def oracle_samples(
    request: Request,
    n: int = Query(60, ge=1, le=100),
) -> OracleSamplesResponse:
    oracle_text_pool: list[str] = getattr(request.app.state, "oracle_text_pool", [])
    home_term_pool: list[str] = getattr(request.app.state, "home_term_pool", [])
    texts = random.sample(oracle_text_pool, min(n, len(oracle_text_pool))) if oracle_text_pool else []
    terms = random.sample(home_term_pool, min(n, len(home_term_pool))) if home_term_pool else []
    return OracleSamplesResponse(texts=texts, terms=terms)


@router.get("/search", response_model=list[CardMatch])
@log_performance(logger=logger)
def search_cards(
    q: str = Query(..., max_length=MAX_QUERY_LENGTH),
    db: Session = Depends(get_db),
    limit: int = Query(10, ge=1, le=MAX_SEARCH_LIMIT),
    offset: int = Query(0, ge=0),
) -> list[CardMatch]:
    ensure_schema_ready()
    if not q.strip():
        return []

    q_norm = q.strip()
    q_lower = q_norm.lower()
    q_like = f"%{q_norm}%"
    q_prefix = f"{q_norm}%"
    face_name_lower = func.lower(CardFace.name)
    match_priority = case(
        (face_name_lower == q_lower, 0),
        (CardFace.name.ilike(q_prefix), 1),
        else_=2,
    )
    faces = (
        db.query(CardFace)
        .options(joinedload(CardFace.card))
        .join(Card, Card.oracle_id == CardFace.oracle_id)
        .filter(CardFace.name.ilike(q_like))
        .order_by(
            match_priority.asc(),
            Card.edhrec_rank.asc().nulls_last(),
            Card.name.asc(),
            CardFace.face_ix.asc(),
            CardFace.name.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        CardMatch(
            name=face.name,
            card_name=face.card.name,
            oracle_id=face.card.oracle_id,
            scryfall_id=face.card.scryfall_id,
            face_ix=face.face_ix,
            image_side=_image_side_for_face(face.card.layout, face.face_ix),
            rank=face.card.edhrec_rank,
        )
        for face in faces
    ]


@router.get("/card/{oracle_id}")
@log_performance(logger=logger)
def get_card_by_id(oracle_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    ensure_schema_ready()
    card = db.query(Card).options(joinedload(Card.faces)).filter(Card.oracle_id == oracle_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card.to_dict()


def _log_semantic_query(
    db: Session,
    request: Request,
    *,
    query_mode: str,
    query_text: str | None,
    oracle_id: str | None,
    face_ix: int | None,
    limit_param: int,
    offset_param: int,
    filters: dict[str, object] | None,
    model_id: str | None,
    result_count: int,
    latency_ms: int,
) -> None:
    try:
        client_ip = request.headers.get("x-real-ip", "").strip() or None
        db.add(
            SemanticQueryLog(
                query_mode=query_mode,
                client_ip=client_ip,
                query_text=query_text,
                oracle_id=oracle_id,
                face_ix=face_ix,
                limit_param=limit_param,
                offset_param=offset_param,
                filters_json=filters or None,
                model_id=model_id,
                result_count=result_count,
                latency_ms=latency_ms,
            )
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001 — logging is best-effort
        logger.warning("Failed to write semantic query log: %s", exc)
        db.rollback()


@router.get("/similar-cards", response_model=SimilarCardsPage)
@log_performance(logger=logger)
def get_similar_cards(
    request: Request,
    db: Session = Depends(get_db),
    oracle_id: str | None = None,
    face_ix: int = Query(0, ge=0),
    q: str | None = Query(None, max_length=MAX_QUERY_LENGTH),
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
    ensure_schema_ready()
    if oracle_id is None and not (q and q.strip()):
        raise HTTPException(status_code=422, detail="Provide either oracle_id or q")

    rarity_list = _parse_rarity(rarity)
    card_type_list = _parse_code_filter(card_type, _CARD_TYPE_MAP, "card type")
    format_list = _parse_code_filter(format, _FORMAT_MAP, "format")

    index = _sem_idx_mod.get_semantic_index()
    if index is None:
        raise HTTPException(status_code=503, detail="Semantic index not available")

    t0 = time.monotonic()
    if oracle_id is not None:
        results = index.similar_to_face(
            (oracle_id, face_ix),
            limit=limit + offset + 1,
            db=db,
            card_type=card_type_list,
            colors=colors,
            cmc_min=cmc_min,
            cmc_max=cmc_max,
            format=format_list,
            rarity=rarity_list,
            color_feature=color_feature,
            match_mode=match_mode,
        )
    else:
        assert q is not None
        results = index.search_oracle(
            q,
            limit=limit + offset + 1,
            db=db,
            card_type=card_type_list,
            colors=colors,
            cmc_min=cmc_min,
            cmc_max=cmc_max,
            format=format_list,
            rarity=rarity_list,
            color_feature=color_feature,
            match_mode=match_mode,
        )

    page_results = results[offset : offset + limit]
    has_more = len(results) > offset + limit
    response = SimilarCardsPage(items=_to_similar_cards(page_results, db), has_more=has_more)
    latency_ms = int((time.monotonic() - t0) * 1000)

    filters: dict[str, object] = {
        k: v
        for k, v in {
            "card_type": card_type,
            "colors": colors,
            "cmc_min": cmc_min,
            "cmc_max": cmc_max,
            "format": format,
            "rarity": rarity,
            "color_feature": color_feature,
            "match_mode": match_mode,
        }.items()
        if v is not None
    }
    _log_semantic_query(
        db,
        request,
        query_mode="by-face" if oracle_id is not None else "text",
        query_text=q,
        oracle_id=oracle_id,
        face_ix=face_ix if oracle_id is not None else None,
        limit_param=limit,
        offset_param=offset,
        filters=filters,
        model_id=index.model_id,
        result_count=len(response.items),
        latency_ms=latency_ms,
    )
    return response
