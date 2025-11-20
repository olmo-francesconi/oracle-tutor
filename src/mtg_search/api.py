import json
import logging
import os
import time
from contextlib import asynccontextmanager
from functools import wraps
from typing import List, Optional, Dict, Any, Callable
from fastapi import FastAPI, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from mtg_search.config import CARD_NAMES_JSON, CARDS_JSON

from .card_name_resolver import CardNameResolver
from .card_oracle_resolver import CardOracleResolver
from .data_builder import update_scryfall_data
from .logging_config import setup_loggers

# Set up logger
setup_loggers()
logger = logging.getLogger("mtg_search.api")


def log_performance(func: Callable) -> Callable:
    """
    Decorator to log the performance of API endpoint calls.
    Times the entire function execution and logs the results.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        # Extract query parameters for logging context (flexible for different endpoints)
        query = kwargs.get('q') or kwargs.get('card_id') or (args[0] if args else '')
        limit = kwargs.get('limit') or (args[1] if len(args) > 1 else None)
        
        # Get result count
        result_count = len(result) if isinstance(result, (list, tuple)) else 1
        
        # Build log message
        log_parts = [f"Found {result_count} matches in {elapsed_ms:.2f} ms"]
        if query:
            log_parts.append(f"query: '{query}'")
        if limit is not None:
            log_parts.append(f"limit: {limit}")
        
        logger.info(", ".join(log_parts))
        
        return result
    return wrapper


# Global variables to hold our data
resolver: Optional[CardNameResolver] = None
oracle_resolver: Optional[CardOracleResolver] = None
cards_by_id: Dict[str, Dict[str, Any]] = {}



def _build_resolver_entries(cards):
    # Prepare data for the resolver
    entries = []
    for card in cards:
        name = card.get("name")
        card_id = card.get("id")
        # Both name and id are required for the resolver
        if not name or not card_id:
            continue
        entry = {
            "id": card_id,
            "name": name,
            "edhrec_rank": card.get("edhrec_rank"),
        }
        entries.append(entry)
    return entries


def _load_card_data():
    """
    Load all card data from disk. This rebuilds the TF-IDF engine
    and all lookup dictionaries.
    """
    global resolver, oracle_resolver, cards_by_id
    
    logger.info("Loading cards from JSON file...")
    # Use streaming JSON parser for large files (same approach as data_builder)
    from importlib import import_module
    ijson = import_module("ijson")
    
    cards = []
    with CARDS_JSON.open("r", encoding="utf-8") as f:
        # ijson.items with "item" path works for JSON arrays
        for card in ijson.items(f, "item"):
            cards.append(card)
    
    logger.info(f"Loaded {len(cards)} cards from disk")

    # Build cards_by_id dictionary for quick lookup
    cards_by_id.clear()
    for card in cards:
        card_id = card.get("id")
        if card_id:
            cards_by_id[card_id] = card

    # Try loading cached index, otherwise build from cards
    try:
        with CARD_NAMES_JSON.open("r", encoding="utf-8") as f:
            resolver_entries =  json.load(f)
    except FileNotFoundError:
        resolver_entries = _build_resolver_entries(cards)

    logger.info("Building name resolver...")
    resolver = CardNameResolver(resolver_entries)
    
    logger.info("Building oracle resolver...")
    # Build oracle resolver entries from all cards
    oracle_entries = []
    for card in cards:
        card_id = card.get("id")
        oracle_text = card.get("oracle_text") or ""
        if card_id and oracle_text:  # Only include cards with oracle text
            oracle_entries.append({
                "id": card_id,
                "name": card.get("name", ""),
                "oracle_text": oracle_text,
                "edhrec_rank": card.get("edhrec_rank"),
            })
    
    logger.info(f"Building oracle resolver with {len(oracle_entries)} cards...")
    oracle_resolver = CardOracleResolver(oracle_entries)
    logger.info("Oracle resolver built successfully")


def _reload_data():
    """
    Reload all card data from disk. This rebuilds the TF-IDF engine
    and all lookup dictionaries.
    """
    logger.info("Reloading card data...")
    _load_card_data()
    logger.info("Data reloaded successfully.")

# Global scheduler instance
_update_scheduler = None

def _start_update_scheduler():
    """Start the background scheduler for daily updates."""
    global _update_scheduler
    
    # Check if scheduler should be enabled (default: True, can be disabled with env var)
    if os.getenv("MTG_SEARCH_DISABLE_SCHEDULER", "").lower() in ("1", "true", "yes"):
        logger.info("Update scheduler disabled via MTG_SEARCH_DISABLE_SCHEDULER environment variable")
        return
    
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from .daily_update import main as update_main
        
        def run_update_with_reload():
            """Run update and reload API data if update was successful."""
            try:
                exit_code = update_main()
                if exit_code == 0:
                    # Reload data after successful update
                    _reload_data()
                    logger.info("Database updated and reloaded successfully")
            except Exception as e:
                logger.error(f"Error in scheduled update: {e}", exc_info=True)
        
        # Get update time from environment or use default (2:00 AM)
        update_hour = int(os.getenv("MTG_SEARCH_UPDATE_HOUR", "2"))
        update_minute = int(os.getenv("MTG_SEARCH_UPDATE_MINUTE", "0"))
        
        _update_scheduler = BackgroundScheduler()
        _update_scheduler.add_job(
            run_update_with_reload,
            trigger=CronTrigger(hour=update_hour, minute=update_minute),
            id="daily_update",
            name="Daily Scryfall database update",
            replace_existing=True,
        )
        _update_scheduler.start()
        logger.info(f"Update scheduler started. Daily updates will run at {update_hour:02d}:{update_minute:02d} local time.")
    except ImportError:
        logger.warning("APScheduler not available. Daily updates will not run automatically.")
        logger.warning("Install with: pip install apscheduler")
    except Exception as e:
        logger.warning(f"Failed to start update scheduler: {e}")


def _stop_update_scheduler():
    """Stop the background scheduler."""
    global _update_scheduler
    if _update_scheduler:
        _update_scheduler.shutdown()
        _update_scheduler = None
        logger.info("Update scheduler stopped.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Load data when the API starts up and start the update scheduler.
    If loading fails, attempt to update data and retry.
    """
    global resolver
    
    logger.info("Loading card data...")
    try:
        _load_card_data()
        logger.info("Data loaded successfully.")
    except (FileNotFoundError, IOError, ValueError) as e:
        logger.error(f"Failed to load card data: {e}")
        logger.info("Running data update and retrying...")
        try:
            update_scryfall_data(force=True)
            logger.info("Data update completed. Retrying load...")
            # Retry loading after update
            _load_card_data()
            logger.info("Data loaded successfully after update.")
        except Exception as update_error:
            logger.critical(f"Failed to update and load data: {update_error}")
            raise RuntimeError("Unable to load card data even after update attempt") from update_error
    
    # Start the update scheduler in the background
    _start_update_scheduler()
    
    yield
    
    # Cleanup: stop the scheduler when the API shuts down
    _stop_update_scheduler()

app = FastAPI(
    lifespan=lifespan,
    title="MTG Search API",
    docs_url=None,
    redoc_url=None
)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models for Response ---

class CardMatch(BaseModel):
    name: str
    similarity: float
    rank: Optional[int] = None
    combined: Optional[float] = None
    id: Optional[str] = None

class CardNameMatch(BaseModel):
    name: str
    id: str

class SimilarCard(BaseModel):
    """Full card data with similarity score for similar cards endpoint."""
    id: str
    name: str
    similarity: float
    rank: Optional[int] = None
    combined: Optional[float] = None
    # Card fields for display
    type_line: Optional[str] = None
    mana_cost: Optional[str] = None
    oracle_text: Optional[str] = None
    rarity: Optional[str] = None

# --- Endpoints ---

@app.get("/favicon.ico")
def favicon():
    """Handle favicon requests to prevent 404 errors in logs."""
    return Response(status_code=204)

@app.get("/search", response_model=List[CardMatch])
@log_performance
def search_cards(q: str, limit: int = 5):
    """
    Fuzzy search for cards by name.
    """
    if not q.strip():
        return []

    if limit > 25:
        limit = 25
    if limit < 1:
        limit = 1
    
    matches = resolver.top_matches(q, limit=limit, rank_weight=0.25)
    
    results = []
    for m in matches:
        results.append(CardMatch(
            name=m["name"],
            similarity=m["similarity"],
            rank=m["rank"],
            id=m["id"],
            combined=m["combined"]
        ))
    
    return results


@app.get("/suggest-names", response_model=List[CardNameMatch])
@log_performance
def search_card_names(q: str, limit: int = 5):
    """
    Search for card names by name. Returns both name and id for each match.
    """
    if not q.strip():
        return []

    if limit > 25:
        limit = 25
    if limit < 1:
        limit = 1
    
    matches = resolver.top_matches(q, limit=limit, rank_weight=0.25)
    
    results = []
    for m in matches:
        results.append(CardNameMatch(
            name=m["name"],
            id=m["id"],
        ))
    
    return results


@app.get("/card/{card_id}")
def get_card_by_id(card_id: str):
    """
    Get card details by ID.
    """
    if card_id not in cards_by_id:
        raise HTTPException(status_code=404, detail="Card not found")
    
    return cards_by_id[card_id]


@app.get("/similar-cards/{card_id}", response_model=List[SimilarCard])
@log_performance
def get_similar_cards(card_id: str, limit: int = 20):
    """
    Find cards similar to the given card based on oracle text similarity.
    Returns full card data with similarity scores.
    """
    if not oracle_resolver:
        raise HTTPException(status_code=503, detail="Oracle resolver not initialized")
    
    if card_id not in cards_by_id:
        raise HTTPException(status_code=404, detail="Card not found")
    
    if limit > 50:
        limit = 50
    if limit < 1:
        limit = 1
    
    matches = oracle_resolver.find_similar_cards(
        card_id=card_id,
        limit=limit,
        min_score=0.1,
        rank_weight=0.15,
    )
    
    results = []
    for m in matches:
        # Get full card data
        card_data = cards_by_id.get(m["id"], {})
        results.append(SimilarCard(
            id=m["id"],
            name=m["name"],
            similarity=m["similarity"],
            rank=m["rank"],
            combined=m["combined"],
            type_line=card_data.get("type_line"),
            mana_cost=card_data.get("mana_cost"),
            oracle_text=card_data.get("oracle_text"),
            rarity=card_data.get("rarity"),
        ))
    
    return results