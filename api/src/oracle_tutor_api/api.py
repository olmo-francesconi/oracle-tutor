import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Dict
from cachetools import TTLCache

from fastapi import FastAPI, Response, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func, desc, or_, cast, Numeric
from sqlalchemy.orm import Session

from .database import get_db
from .models import Card, CardFace
from .logging_config import setup_loggers, log_performance
from .text_processing import expand_symbols

from sentence_transformers import SentenceTransformer

# Set up logger
setup_loggers()
logger = logging.getLogger("oracle_tutor_api.api")

# Global model instance
_model = None

# In-memory cache for search results (ID lists)
# Key: (query_str, card_type, colors)
# Value: List of (face_id, distance)
_search_cache = TTLCache(maxsize=100, ttl=600)  # 10 minutes TTL

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    On startup, ensure the database has data.
    """
    global _model
    logger.info("API Starting...")
    
    logger.info("Loading embedding model...")
    _model = SentenceTransformer('all-MiniLM-L6-v2')
    
    yield

app = FastAPI(
    lifespan=lifespan,
    title="Oracle Tutor API (Postgres Version)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex="https?://.*",  # Allow all origins with credentials
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models ---

class CardMatch(BaseModel):
    name: str
    similarity: float = 1.0
    rank: Optional[int] = None
    id: Optional[str] = None

class CardNameMatch(BaseModel):
    name: str
    id: str

class SimilarCard(BaseModel):
    id: str
    name: str # Face name
    card_name: str # Full Card name
    similarity: float
    rank: Optional[int] = None
    
    # Display fields from Face
    type_line: Optional[str] = None
    mana_cost: Optional[str] = None
    oracle_text: Optional[str] = None
    power: Optional[str] = None
    toughness: Optional[str] = None
    colors: Optional[List[str]] = None
    
    # Fields from Card
    layout: Optional[str] = None
    rarity: Optional[str] = None
    legalities: Optional[Dict[str, str]] = None

# --- Endpoints ---

@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)

@app.get("/search", response_model=List[CardMatch])
@log_performance(logger=logger)
def search_cards(q: str, limit: int = 5, db: Session = Depends(get_db)):
    """
    Search for cards by name using fuzzy search (pg_trgm).
    Searches the parent card name (which usually includes both faces for split/DFC).
    """
    if not q.strip():
        return []

    limit = max(1, min(limit, 25))
    
    # Use pg_trgm distance operator <->
    distance = Card.name.op("<->")(q)
    
    results = (
        db.query(Card, distance.label("dist"))
        .filter(or_(
            Card.name.op("%")(q),
            Card.name.ilike(f"%{q}%")
        ))
        .order_by(distance, Card.edhrec_rank.asc().nulls_last())
        .limit(limit)
        .all()
    )
    
    return [
        CardMatch(
            name=c.name, 
            id=c.id, 
            rank=c.edhrec_rank, 
            similarity=1.0 - dist
        )
        for c, dist in results
    ]

@app.get("/suggest-names", response_model=List[CardNameMatch])
@log_performance(logger=logger)
def search_card_names(q: str, limit: int = 5, db: Session = Depends(get_db)):
    """
    Autocomplete endpoint using fuzzy search.
    """
    if not q.strip():
        return []

    limit = max(1, min(limit, 25))

    distance = Card.name.op("<->")(q)

    cards = (
        db.query(Card.name, Card.id)
        .filter(or_(
            Card.name.op("%")(q),
            Card.name.ilike(f"%{q}%")
        ))
        .order_by(distance, Card.edhrec_rank.asc().nulls_last())
        .limit(limit)
        .all()
    )
    
    return [CardNameMatch(name=c.name, id=c.id) for c in cards]

@app.get("/card/{card_id}")
@log_performance(logger=logger)
def get_card_by_id(card_id: str, db: Session = Depends(get_db)):
    """
    Get single card details.
    """
    card = db.get(Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
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
    db: Session = Depends(get_db)
):
    """
    Vector similarity search using pgvector.
    Targets specific face of the source card.
    Returns matching Faces (joined with their Cards).
    Uses caching to speed up pagination.
    """
    # Check Cache First
    # Cache key includes all filter params
    cache_key = (f"similar-{card_id}-{face_index}", card_type, colors, format)
    
    if cache_key in _search_cache:
        cached_results = _search_cache[cache_key]
    else:
        # 1. Get the target card to find its embedding
        target_card = db.get(Card, card_id)
        if not target_card:
            raise HTTPException(status_code=404, detail="Card not found")
        
        if not target_card.faces:
            raise HTTPException(status_code=404, detail="Card has no faces data")
            
        if face_index >= len(target_card.faces):
             raise HTTPException(status_code=400, detail="Invalid face_index")

        target_face = target_card.faces[face_index]
        if target_face.embedding is None:
            raise HTTPException(status_code=400, detail="Card face has no embedding for comparison")

        # 2. Build Query for IDs only
        distance_col = CardFace.embedding.cosine_distance(target_face.embedding).label("distance")
        
        query = (
            db.query(CardFace.id, distance_col)
            .join(Card, CardFace.card_id == Card.id)
            .filter(Card.id != card_id) # Exclude the source card entirely
        )

        # 3. Apply Filters
        if card_type:
            types = [t.strip() for t in card_type.split(",") if t.strip()]
            # Filter on CardFace.type_line
            type_filters = [CardFace.type_line.ilike(f"%{t}%") for t in types]
            if type_filters:
                query = query.filter(or_(*type_filters))

        if colors:
            # Strict text match on colors JSON for now, or implement containment
            pass 

        # 4. Order by Similarity (rounded to 3 decimals) desc, then Name asc
        query = query.order_by(
            func.round(cast(1 - distance_col, Numeric), 3).desc(),
            CardFace.name.asc()
        )
        
        # 5. Fetch larger batch for caching
        query = query.limit(1000)
        
        raw_results = query.all()
        cached_results = [(r[0], r[1]) for r in raw_results]
        _search_cache[cache_key] = cached_results
        
    # 6. Pagination from Cache
    sliced_results = cached_results[offset : offset + limit]
    
    if not sliced_results:
        return []

    # 7. Hydrate full card details
    target_ids = [r[0] for r in sliced_results]
    id_to_dist = {r[0]: r[1] for r in sliced_results}
    
    cards_data = (
        db.query(CardFace, Card)
        .join(Card, CardFace.card_id == Card.id)
        .filter(CardFace.id.in_(target_ids))
        .all()
    )
    
    cards_map = {face.id: (face, card) for face, card in cards_data}
            
    # 8. Format Response
    output = []
    for face_id in target_ids:
        if face_id in cards_map:
            face, card = cards_map[face_id]
            distance = id_to_dist[face_id]
            similarity = 1 - distance
            
            output.append(SimilarCard(
                id=card.id,
                name=face.name,
                card_name=card.name,
                similarity=similarity,
                rank=card.edhrec_rank,
                type_line=face.type_line,
                mana_cost=face.mana_cost,
                oracle_text=face.oracle_text,
                power=face.power,
                toughness=face.toughness,
                layout=card.layout,
                rarity=card.rarity,
                colors=face.colors,
                legalities=card.legalities
            ))
    
    return output

@app.get("/search-oracle", response_model=List[SimilarCard])
@log_performance(logger=logger)
def search_oracle_text(
    q: str,
    limit: int = 20,
    offset: int = 0,
    card_type: Optional[str] = Query(None),
    colors: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Search for cards by oracle text using vector similarity.
    Uses caching to speed up pagination.
    """
    if not q.strip():
        return []
        
    # Check Cache First
    cache_key = (q.strip(), card_type, colors)
    
    if cache_key in _search_cache:
        cached_results = _search_cache[cache_key]
    else:
        # 1. Preprocess and Embed Query
        expanded_query = expand_symbols(q)
        if not expanded_query.strip():
            return []

        if _model is None:
             raise HTTPException(status_code=503, detail="Model not loaded yet")
             
        query_embedding = _model.encode(expanded_query, convert_to_tensor=False).tolist()

        # 2. Build Query for IDs only (Lightweight)
        distance_col = CardFace.embedding.cosine_distance(query_embedding).label("distance")
        
        query = (
            db.query(CardFace.id, distance_col)
            .join(Card, CardFace.card_id == Card.id)
        )

        # 3. Apply Filters
        if card_type:
            types = [t.strip() for t in card_type.split(",") if t.strip()]
            type_filters = [CardFace.type_line.ilike(f"%{t}%") for t in types]
            if type_filters:
                query = query.filter(or_(*type_filters))

        if colors:
            # Strict text match on colors JSON for now
            pass 

        # 4. Order by Similarity (rounded to 3 decimals) desc, then Name asc
        query = query.order_by(
            func.round(cast(1 - distance_col, Numeric), 3).desc(),
            CardFace.name.asc()
        )
        
        # 5. Fetch larger batch for caching (e.g., top 1000)
        # This covers most pagination needs without re-querying vector index
        query = query.limit(1000)
        
        raw_results = query.all()
        # Store list of (id, distance)
        cached_results = [(r[0], r[1]) for r in raw_results]
        _search_cache[cache_key] = cached_results

    # 6. Pagination from Cache
    sliced_results = cached_results[offset : offset + limit]
    
    if not sliced_results:
        return []
        
    # 7. Hydrate full card details
    target_ids = [r[0] for r in sliced_results]
    id_to_dist = {r[0]: r[1] for r in sliced_results}
    
    # Fetch full objects for the slice
    cards_data = (
        db.query(CardFace, Card)
        .join(Card, CardFace.card_id == Card.id)
        .filter(CardFace.id.in_(target_ids))
        .all()
    )
    
    # Map back to preserve order
    cards_map = {face.id: (face, card) for face, card in cards_data}

    output = []
    for face_id in target_ids:
        if face_id in cards_map:
            face, card = cards_map[face_id]
            distance = id_to_dist[face_id]
            similarity = 1 - distance
            
            output.append(SimilarCard(
                id=card.id,
                name=face.name,
                card_name=card.name,
                similarity=similarity,
                rank=card.edhrec_rank,
                type_line=face.type_line,
                mana_cost=face.mana_cost,
                oracle_text=face.oracle_text,
                power=face.power,
                toughness=face.toughness,
                layout=card.layout,
                rarity=card.rarity,
                colors=face.colors,
                legalities=card.legalities
            ))
    
    return output
