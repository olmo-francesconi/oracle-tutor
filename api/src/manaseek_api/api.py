import json
import logging
import os
import time
from contextlib import asynccontextmanager
from functools import wraps
from typing import List, Optional, Dict, Any, Callable
from fastapi import FastAPI, Response, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from manaseek_api.config import CARD_NAMES_JSON, CARDS_JSON

from .card_name_resolver import CardNameResolver
from .card_oracle_resolver import CardOracleResolver
from .data_builder import update_scryfall_data
from .logging_config import setup_loggers
from .memory_utils import log_memory_report

# Set up logger
setup_loggers()
logger = logging.getLogger("manaseek_api.api")


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
    if os.getenv("MANASEEK_API_DISABLE_SCHEDULER", "").lower() in ("1", "true", "yes"):
        logger.info("Update scheduler disabled via MANASEEK_API_DISABLE_SCHEDULER environment variable")
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
        update_hour = int(os.getenv("MANASEEK_API_UPDATE_HOUR", "2"))
        update_minute = int(os.getenv("MANASEEK_API_UPDATE_MINUTE", "0"))
        
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
    
    # Log memory report after everything is loaded
    log_memory_report(resolver, oracle_resolver, cards_by_id)
    
    yield
    
    # Cleanup: stop the scheduler when the API shuts down
    _stop_update_scheduler()

app = FastAPI(
    lifespan=lifespan,
    title="ManaSeek API",
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
    colors: Optional[List[str]] = None
    legalities: Optional[Dict[str, str]] = None

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
def get_similar_cards(
    card_id: str, 
    limit: int = 20, 
    offset: int = 0,
    card_type: Optional[str] = Query(None, description="Filter by card type (comma-separated, e.g., 'Creature,Instant' or 'Sorcery')"),
    colors: Optional[str] = Query(None, description="Filter by colors (comma-separated, e.g., 'R,W' or 'U' or 'C' for colorless)"),
    format: Optional[str] = Query(None, description="Filter by format legality (comma-separated, e.g., 'standard,modern' or 'commander')")
):
    """
    Find cards similar to the given card based on oracle text similarity.
    Returns full card data with similarity scores.
    
    Supports pagination via offset parameter and filtering by card type, colors, and format.
    """
    if not oracle_resolver:
        raise HTTPException(status_code=503, detail="Oracle resolver not initialized")
    
    if card_id not in cards_by_id:
        raise HTTPException(status_code=404, detail="Card not found")
    
    if limit > 50:
        limit = 50
    if limit < 1:
        limit = 1
    
    if offset < 0:
        offset = 0
    
    # Parse filter parameters
    filter_colors = None
    if colors:
        filter_colors = [c.strip().upper() for c in colors.split(",") if c.strip()]
    
    filter_card_types = None
    if card_type:
        filter_card_types = [t.strip() for t in card_type.split(",") if t.strip()]
    
    filter_formats = None
    if format:
        filter_formats = [f.strip().lower() for f in format.split(",") if f.strip()]
    
    # Get a larger set of matches to filter from (we'll filter and then paginate)
    # Fetch more results to account for filtering and offset
    has_filters = filter_card_types or filter_colors or filter_formats
    if has_filters:
        # When filtering, we need to fetch more to account for filtering and offset
        fetch_limit = (limit + offset) * 5
        # Cap at reasonable maximum to avoid performance issues
        fetch_limit = min(fetch_limit, 500)
    else:
        fetch_limit = limit + offset
    
    matches = oracle_resolver.find_similar_cards(
        card_id=card_id,
        limit=fetch_limit,
        offset=0,  # Start from beginning, we'll handle offset after filtering
        min_score=0.1,
        rank_weight=0.15,
    )
    
    results = []
    skipped = 0
    
    for m in matches:
        # Get full card data
        card_data = cards_by_id.get(m["id"], {})
        
        # Apply filters
        if filter_card_types:
            type_line = card_data.get("type_line", "")
            # Check if any of the selected card types match
            if not any(ct.lower() in type_line.lower() for ct in filter_card_types):
                continue
        
        if filter_colors:
            card_colors = card_data.get("colors", [])
            card_has_colors = len(card_colors) > 0
            card_is_colorless = not card_has_colors
            
            # Separate colorless from other color filters
            has_colorless_filter = "C" in filter_colors
            other_color_filters = [c for c in filter_colors if c != "C"]
            
            # Check if card matches any of the selected filters
            matches_colorless = has_colorless_filter and card_is_colorless
            matches_colors = False
            if other_color_filters and card_has_colors:
                matches_colors = any(c.upper() in [col.upper() for col in card_colors] for c in other_color_filters)
            
            # Include card if it matches colorless filter OR color filters
            if not (matches_colorless or matches_colors):
                continue
        
        if filter_formats:
            # Check if card is legal in any of the selected formats
            legalities = card_data.get("legalities", {})
            is_legal_in_any = any(
                legalities.get(fmt, "").lower() == "legal" 
                for fmt in filter_formats
            )
            if not is_legal_in_any:
                continue
        
        # Apply offset after filtering
        if skipped < offset:
            skipped += 1
            continue
        
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
            colors=card_data.get("colors"),
            legalities=card_data.get("legalities"),
        ))
        
        if len(results) == limit:
            break
    
    return results