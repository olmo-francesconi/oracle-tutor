import os
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.security import APIKeyHeader, APIKeyQuery
from pydantic import BaseModel

from .card_data import (
    build_card_lookup_by_id,
    build_card_lookup_by_name,
    load_card_name_index,
    load_cards,
)
from .card_name_resolver import CardNameResolver

# Global variables to hold our data
resolver: Optional[CardNameResolver] = None
card_lookup_by_id: Dict[str, Dict[str, Any]] = {}
card_lookup_by_name: Dict[str, Dict[str, Any]] = {}
name_to_id: Dict[str, str] = {}
name_to_rank: Dict[str, Optional[int]] = {}

# Global scheduler instance
_update_scheduler = None

def _build_resolver_entries(cards):
    # Logic adapted from cli.py to prepare data for the resolver
    entries = []
    for card in cards:
        name = card.get("name")
        if not name:
            continue
        entry = {
            "name": name,
            "edhrec_rank": card.get("edhrec_rank"),
        }
        if card.get("id"):
            entry["id"] = card["id"]
        entries.append(entry)
    return entries


def _reload_data():
    """
    Reload all card data from disk. This rebuilds the TF-IDF engine
    and all lookup dictionaries.
    """
    global resolver, card_lookup_by_id, card_lookup_by_name, name_to_id, name_to_rank
    
    print("Reloading card data...")
    cards = load_cards()
    card_lookup_by_name = build_card_lookup_by_name(cards)
    card_lookup_by_id = build_card_lookup_by_id(cards)

    # Try loading cached index, otherwise build from cards
    try:
        resolver_entries = load_card_name_index()
    except FileNotFoundError:
        resolver_entries = _build_resolver_entries(cards)

    resolver = CardNameResolver(resolver_entries)
    
    # Build helper lookups
    name_to_id = {entry["name"]: entry["id"] for entry in resolver_entries if entry.get("id")}
    name_to_rank = {entry["name"]: entry.get("edhrec_rank") for entry in resolver_entries}
    
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
    """
    global resolver, card_lookup_by_id, card_lookup_by_name, name_to_id, name_to_rank
    
    print("Loading card data...")
    cards = load_cards()
    card_lookup_by_name = build_card_lookup_by_name(cards)
    card_lookup_by_id = build_card_lookup_by_id(cards)

    # Try loading cached index, otherwise build from cards
    try:
        resolver_entries = load_card_name_index()
    except FileNotFoundError:
        resolver_entries = _build_resolver_entries(cards)

    resolver = CardNameResolver(resolver_entries)
    
    # Build helper lookups
    name_to_id = {entry["name"]: entry["id"] for entry in resolver_entries if entry.get("id")}
    name_to_rank = {entry["name"]: entry.get("edhrec_rank") for entry in resolver_entries}
    
    print("Data loaded successfully.")
    
    # Check if API key is configured
    if not os.getenv("MTG_SEARCH_API_KEY"):
        print("⚠️  WARNING: No API key configured (MTG_SEARCH_API_KEY). Admin endpoints are unprotected!")
        print("   Set MTG_SEARCH_API_KEY environment variable to secure admin endpoints.")
    
    # Start the update scheduler in the background
    _start_update_scheduler()
    
    yield
    
    # Cleanup: stop the scheduler when the API shuts down
    _stop_update_scheduler()

app = FastAPI(lifespan=lifespan, title="MTG Search API")

# --- Security ---

# API Key authentication
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)


def get_api_key(
    api_key_header: Optional[str] = Security(api_key_header),
    api_key_query: Optional[str] = Security(api_key_query),
) -> str:
    """
    Verify API key from header or query parameter.
    Admin endpoints require a valid API key.
    """
    # Get the expected API key from environment
    expected_api_key = os.getenv("MTG_SEARCH_API_KEY")
    
    # If no API key is configured, allow access (for development)
    if not expected_api_key:
        # In production, you should set an API key!
        return "no-key-configured"
    
    # Check header first, then query parameter
    provided_key = api_key_header or api_key_query
    
    if not provided_key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Provide it via X-API-Key header or api_key query parameter.",
        )
    
    if provided_key != expected_api_key:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key.",
        )
    
    return provided_key

# --- Pydantic Models for Response ---

class CardMatch(BaseModel):
    name: str
    similarity: float
    rank: Optional[int] = None
    id: Optional[str] = None

class CardDetails(BaseModel):
    id: str
    name: str
    mana_cost: Optional[str] = None
    type_line: Optional[str] = None
    oracle_text: Optional[str] = None
    edhrec_rank: Optional[int] = None
    # Add other fields from your JSON data as needed

# --- Endpoints ---

@app.get("/search", response_model=List[CardMatch])
def search_cards(q: str, limit: int = 5):
    """
    Fuzzy search for cards by name.
    """
    if not q.strip():
        return []
        
    # Use the same top_matches logic as your CLI
    matches = resolver.top_matches(q, limit=limit, rank_weight=0.25)
    
    results = []
    for name, similarity, _combined in matches:
        results.append(CardMatch(
            name=name,
            similarity=similarity,
            rank=name_to_rank.get(name),
            id=name_to_id.get(name)
        ))
    return results

@app.get("/cards/{card_id}", response_model=CardDetails)
def get_card(card_id: str):
    """
    Get full details for a specific card by ID.
    """
    card = card_lookup_by_id.get(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@app.post("/reload")
def reload_data(api_key: str = Depends(get_api_key)):
    """
    Reload card data from disk. Useful after running the daily update script.
    This rebuilds the TF-IDF engine and all lookup dictionaries.
    
    **Requires API key authentication.**
    """
    try:
        _reload_data()
        return {"status": "success", "message": "Data reloaded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reloading data: {str(e)}")


@app.get("/scheduler/status")
def get_scheduler_status(api_key: str = Depends(get_api_key)):
    """
    Get the status of the update scheduler.
    
    **Requires API key authentication.**
    """
    global _update_scheduler
    if _update_scheduler is None:
        return {
            "enabled": False,
            "message": "Scheduler is not running (may be disabled or APScheduler not available)"
        }
    
    jobs = _update_scheduler.get_jobs()
    if jobs:
        job = jobs[0]
        return {
            "enabled": True,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "job_id": job.id,
            "job_name": job.name
        }
    return {
        "enabled": True,
        "message": "Scheduler is running but no jobs are scheduled"
    }


@app.post("/scheduler/update-now")
def trigger_update_now(api_key: str = Depends(get_api_key)):
    """
    Manually trigger an update check and reload data if updates are available.
    
    **Requires API key authentication.**
    """
    try:
        from .daily_update import main as update_main
        
        exit_code = update_main()
        if exit_code == 0:
            # Reload data after successful update
            _reload_data()
            return {
                "status": "success",
                "message": "Update check completed. Data reloaded if updates were available."
            }
        else:
            return {
                "status": "error",
                "message": "Update check failed"
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during update: {str(e)}")