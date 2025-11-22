import logging
import os
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, Response, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func, desc, or_
from sqlalchemy.orm import Session

from .database import get_db
from .models import Card, CardFace
from .data_builder import update_scryfall_data
from .logging_config import setup_loggers, log_performance

# Set up logger
setup_loggers()
logger = logging.getLogger("oracle_tutor_api.api")

# Global scheduler instance
_update_scheduler = None

def _start_update_scheduler():
    """Start the background scheduler for daily updates."""
    global _update_scheduler
    
    if os.getenv("ORACLE_TUTOR_API_DISABLE_SCHEDULER", "").lower() in ("1", "true", "yes"):
        logger.info("Scheduler disabled.")
        return
    
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        
        def run_update():
            """Run update process."""
            try:
                logger.info("Running scheduled database update...")
                # This now updates the Postgres DB directly
                updated = update_scryfall_data(force=False)
                if updated:
                    logger.info("Scheduled update completed successfully.")
                else:
                    logger.info("No updates found.")
            except Exception as e:
                logger.error(f"Error in scheduled update: {e}", exc_info=True)
        
        # Default to 2:00 AM
        update_hour = int(os.getenv("ORACLE_TUTOR_API_UPDATE_HOUR", "2"))
        
        _update_scheduler = BackgroundScheduler()
        _update_scheduler.add_job(
            run_update,
            trigger=CronTrigger(hour=update_hour, minute=0),
            id="daily_update",
            name="Daily Scryfall database update",
            replace_existing=True,
        )
        _update_scheduler.start()
        logger.info(f"Scheduler started (Daily at {update_hour}:00).")
    except ImportError:
        logger.warning("APScheduler not installed.")
    except Exception as e:
        logger.warning(f"Failed to start scheduler: {e}")

def _stop_update_scheduler():
    global _update_scheduler
    if _update_scheduler:
        _update_scheduler.shutdown()
        _update_scheduler = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    On startup, ensure the database has data.
    """
    logger.info("API Starting...")
    
    # Check if we need to seed the DB on first run
    # We run this in a way that doesn't block indefinitely, but ensures tables exist
    try:
        logger.info("Checking database status...")
        # This handles init_db and initial download if missing
        update_scryfall_data(force=False)
    except Exception as e:
        logger.error(f"Startup data check failed: {e}")
        # We continue anyway; maybe the DB is fine, just network failed
    
    _start_update_scheduler()
    yield
    _stop_update_scheduler()

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
    """
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

    # 2. Build Query
    # We search for Faces, but join Card to get parent info
    distance_col = CardFace.embedding.cosine_distance(target_face.embedding).label("distance")
    
    query = (
        db.query(CardFace, Card, distance_col)
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

    # 4. Order by Vector Distance
    query = query.order_by(distance_col.asc())
    
    # 5. Pagination
    query = query.offset(offset).limit(limit)
    
    results = query.all()
            
    # 6. Format Response
    output = []
    for face, card, distance in results:
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
            rarity=card.rarity,
            colors=face.colors,
            legalities=card.legalities
        ))
    
    return output
