import json
import os
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any
from fastapi import FastAPI
from pydantic import BaseModel

from mtg_search.config import CARD_NAMES_JSON, CARDS_JSON

from .card_name_resolver import CardNameResolver
from .data_builder import update_scryfall_data

# Global variables to hold our data
resolver: Optional[CardNameResolver] = None
# card_lookup_by_name: Dict[str, Dict[str, Any]] = {}
# name_to_id: Dict[str, str] = {}
# name_to_rank: Dict[str, Optional[int]] = {}

# Global scheduler instance
_update_scheduler = None

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
    global resolver
    
    with CARDS_JSON.open("r", encoding="utf-8") as f:
        cards = json.load(f)

    # Try loading cached index, otherwise build from cards
    try:
        with CARD_NAMES_JSON.open("r", encoding="utf-8") as f:
            resolver_entries =  json.load(f)
    except FileNotFoundError:
        resolver_entries = _build_resolver_entries(cards)

    resolver = CardNameResolver(resolver_entries)


def _reload_data():
    """
    Reload all card data from disk. This rebuilds the TF-IDF engine
    and all lookup dictionaries.
    """
    print("Reloading card data...")
    _load_card_data()
    print("Data reloaded successfully.")

def _start_update_scheduler():
    """Start the background scheduler for daily updates."""
    global _update_scheduler
    
    # Check if scheduler should be enabled (default: True, can be disabled with env var)
    if os.getenv("MTG_SEARCH_DISABLE_SCHEDULER", "").lower() in ("1", "true", "yes"):
        print("Update scheduler disabled via MTG_SEARCH_DISABLE_SCHEDULER environment variable")
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
                    print("Database updated and reloaded successfully")
            except Exception as e:
                print(f"Error in scheduled update: {e}")
        
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
        print(f"Update scheduler started. Daily updates will run at {update_hour:02d}:{update_minute:02d} local time.")
    except ImportError:
        print("Warning: APScheduler not available. Daily updates will not run automatically.")
        print("Install with: pip install apscheduler")
    except Exception as e:
        print(f"Warning: Failed to start update scheduler: {e}")


def _stop_update_scheduler():
    """Stop the background scheduler."""
    global _update_scheduler
    if _update_scheduler:
        _update_scheduler.shutdown()
        _update_scheduler = None
        print("Update scheduler stopped.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Load data when the API starts up and start the update scheduler.
    If loading fails, attempt to update data and retry.
    """
    global resolver
    
    print("Loading card data...")
    try:
        _load_card_data()
        print("Data loaded successfully.")
    except (FileNotFoundError, IOError, ValueError) as e:
        print(f"Failed to load card data: {e}")
        print("Running data update and retrying...")
        try:
            update_scryfall_data(force=True)
            print("Data update completed. Retrying load...")
            # Retry loading after update
            _load_card_data()
            print("Data loaded successfully after update.")
        except Exception as update_error:
            print(f"Failed to update and load data: {update_error}")
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

# --- Pydantic Models for Response ---

class CardMatch(BaseModel):
    name: str
    similarity: float
    rank: Optional[int] = None
    combined: Optional[float] = None
    id: Optional[str] = None

# --- Endpoints ---

@app.get("/search", response_model=List[CardMatch])
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