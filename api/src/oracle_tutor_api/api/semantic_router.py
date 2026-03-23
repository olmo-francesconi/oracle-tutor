from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.models import CardFace
from .schemas import SimilarCard

router = APIRouter(prefix="/semantic", tags=["semantic"])


def _get_semantic_index():
    try:
        from ..semantic.index import get_semantic_index
    except ImportError:
        return None
    return get_semantic_index()


def _to_similar_cards(results: list[tuple[int, float]], db: Session) -> List[SimilarCard]:
    if not results:
        return []

    target_face_ids = [face_id for face_id, _ in results]
    id_to_score = {face_id: score for face_id, score in results}
    cards_data = (
        db.query(CardFace)
        .filter(CardFace.id.in_(target_face_ids))
        .all()
    )
    faces_map = {face.id: face for face in cards_data}

    out: List[SimilarCard] = []
    for face_id in target_face_ids:
        face = faces_map.get(face_id)
        if face is None:
            continue
        card = face.card
        out.append(
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
    return out


@router.get("/similar-cards/{card_id}", response_model=List[SimilarCard])
def semantic_similar_cards(
    card_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    index = _get_semantic_index()
    if index is None:
        raise HTTPException(status_code=503, detail="Semantic index not available")

    face = (
        db.query(CardFace)
        .filter(CardFace.card_id == card_id)
        .order_by(CardFace.id.asc())
        .first()
    )
    if face is None:
        raise HTTPException(status_code=404, detail="Card not found")

    results = index.similar_to_face(face.id, limit=limit + offset, db=db)
    return _to_similar_cards(results[offset:], db)


@router.get("/search-oracle", response_model=List[SimilarCard])
def semantic_search_oracle(
    q: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if not q.strip():
        return []

    index = _get_semantic_index()
    if index is None:
        raise HTTPException(status_code=503, detail="Semantic index not available")

    results = index.search_oracle(q, limit=limit + offset, db=db)
    return _to_similar_cards(results[offset:], db)
