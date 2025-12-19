import logging
import ijson
import re
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple

import requests
from sqlalchemy import text, delete, inspect, func
from sqlalchemy.dialects.postgresql import insert

from .config import CARDS_JSON, DATA_DIR, DB_SCHEMA_VERSION
from .database import SessionLocal, engine
from .models import Base, Card, CardFace, SystemMetadata, IngestionLog
from .logging_config import setup_loggers
from .text_processing import expand_symbols

logger = logging.getLogger("oracle_tutor_api.data")

BULK_DATA_URL = "https://api.scryfall.com/bulk-data/oracle-cards"
BATCH_SIZE = 500  # Process cards in batches to save memory
META_JSON = DATA_DIR / "scryfall_meta.json"
TEMP_CARDS_JSON = DATA_DIR / "scryfall-cards-temp.json"

def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

def fetch_bulk_metadata(url: str = BULK_DATA_URL) -> Dict[str, Any]:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()

def save_local_metadata(metadata: Dict[str, Any]) -> None:
    """Save Scryfall metadata to a local JSON file."""
    with META_JSON.open("w") as f:
        json.dump(metadata, f, indent=2)

def load_local_metadata() -> Optional[Dict[str, Any]]:
    """Load Scryfall metadata from local JSON file if exists."""
    if not META_JSON.exists():
        return None
    try:
        with META_JSON.open("r") as f:
            return json.load(f)
    except Exception:
        return None

def download_bulk_file(download_url: str, destination: Path = CARDS_JSON) -> None:
    """Download the Scryfall bulk data to a local file."""
    logger.info(f"Downloading bulk data from {download_url} to {destination}...")
    with requests.get(download_url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with destination.open("wb") as outfile:
            for chunk in resp.iter_content(chunk_size=1_048_576):
                if chunk:
                    outfile.write(chunk)
    logger.info("Download complete.")

def init_db():
    """Create tables and enable vector extension."""
    logger.info("Initializing database...")
    
    # Check schema version
    inspector = inspect(engine)
    has_cards = inspector.has_table("cards")
    has_faces = inspector.has_table("card_faces")
    has_logs = inspector.has_table("ingestion_logs")
    
    # Check specific columns
    has_sys_meta = inspector.has_table("system_metadata")
    sys_meta_cols = [c['name'] for c in inspector.get_columns("system_metadata")] if has_sys_meta else []
    has_schema_version = "schema_version" in sys_meta_cols
    
    card_cols = [c['name'] for c in inspector.get_columns("cards")] if has_cards else []
    has_layout_col = "layout" in card_cols
    
    log_cols = [c['name'] for c in inspector.get_columns("ingestion_logs")] if has_logs else []
    has_skipped_col = "records_skipped" in log_cols
    
    with engine.begin() as conn:
        # Schema Migration Check
        if (has_cards and not has_faces) or (has_sys_meta and not has_schema_version) or (has_logs and not has_skipped_col) or (has_cards and not has_layout_col):
            logger.warning("Old schema detected. Dropping old tables to rebuild...")
            conn.execute(text("DROP TABLE IF EXISTS cards CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS system_metadata CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS ingestion_logs CASCADE"))
            
        # Enable pgvector extension
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Enable pg_trgm extension for fuzzy search
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        # Create tables
        Base.metadata.create_all(conn)
        # Create GIN index for fuzzy search on name if it doesn't exist
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cards_name_trgm ON cards USING gin (name gin_trgm_ops)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_card_faces_name_trgm ON card_faces USING gin (name gin_trgm_ops)"))
    logger.info("Database initialized.")

def prepare_parent_card(card_data: dict) -> dict:
    """Transform JSON data into a dictionary matching the Card model."""
    return {
        "id": card_data.get("id"),
        "name": card_data.get("name"),
        "layout": card_data.get("layout"),
        "edhrec_rank": card_data.get("edhrec_rank"),
        "rarity": card_data.get("rarity"),
        "legalities": card_data.get("legalities"),
    }

def prepare_card_face(card_id: str, face_data: dict, embedding: List[float]) -> dict:
    """Transform JSON face data into a dictionary matching the CardFace model."""
    return {
        "card_id": card_id,
        "name": face_data.get("name"),
        "mana_cost": face_data.get("mana_cost"),
        "type_line": face_data.get("type_line"),
        "oracle_text": face_data.get("oracle_text"),
        "power": face_data.get("power"),
        "toughness": face_data.get("toughness"),
        "colors": face_data.get("colors"),
        "embedding": embedding
    }

def normalize_card_data(card: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts the subset of card data that we store in the database.
    Used for comparing old vs new data to detect changes.
    """
    # 1. Parent Data
    normalized = {
        "id": card.get("id"),
        "name": card.get("name"),
        "layout": card.get("layout"),
        "edhrec_rank": card.get("edhrec_rank"),
        "rarity": card.get("rarity"),
        "legalities": card.get("legalities"),
    }
    
    # 2. Faces Data
    faces = card.get("card_faces")
    if not faces:
        faces = [card]
        
    normalized_faces = []
    for face in faces:
        normalized_faces.append({
            "name": face.get("name"),
            "mana_cost": face.get("mana_cost"),
            "type_line": face.get("type_line"),
            "oracle_text": face.get("oracle_text"),
            "power": face.get("power"),
            "toughness": face.get("toughness"),
            "colors": face.get("colors"),
        })
    
    normalized["faces"] = normalized_faces
    return normalized

def should_skip_card(card: Dict[str, Any]) -> bool:
    """Determines if a card should be skipped based on layout."""
    return card.get("layout") in [
        "token", 
        "double_faced_token", 
        "art_series", 
        "emblem", 
        "planar", 
        "scheme", 
        "vanguard"
    ]

def load_existing_cards_map(file_path: Path) -> Dict[str, Dict[str, Any]]:
    """Loads the entire existing card dataset into memory as a map of ID -> Normalized Data."""
    if not file_path.exists():
        return {}
    
    logger.info(f"Loading existing data from {file_path} for comparison...")
    try:
        with file_path.open("r") as f:
            # Use json.load since we need the whole thing and it fits in memory (~60MB)
            # Iterating with ijson is slower for building a full dict
            data = json.load(f)
            
        card_map = {}
        for card in data:
            if not should_skip_card(card):
                card_map[card.get("id")] = normalize_card_data(card)
        
        logger.info(f"Loaded {len(card_map)} existing cards.")
        return card_map
    except Exception as e:
        logger.warning(f"Failed to load existing file {file_path}: {e}. treating as empty.")
        return {}

def ingest_batch(session, model, batch_cards: List[Dict[str, Any]]):
    """Helper to ingest a batch of cards (Upsert Parent, Insert Faces)."""
    if not batch_cards:
        return

    batch_parents = []
    batch_faces_data = []
    batch_texts = []

    for card in batch_cards:
        # 1. Prepare Parent
        batch_parents.append(prepare_parent_card(card))
        
        # 2. Prepare Faces
        faces = card.get("card_faces")
        if not faces:
            faces = [card]
        
        for face in faces:
            oracle_text = face.get("oracle_text", "") or ""
            face_name = face.get("name", "")
            expanded_text = expand_symbols(oracle_text, card_name=face_name)
            text_to_embed = f"{expanded_text}"
            
            batch_texts.append(text_to_embed)
            batch_faces_data.append((card.get("id"), face))

    # A. Upsert Parents
    stmt_parent = insert(Card).values(batch_parents)
    stmt_parent = stmt_parent.on_conflict_do_update(
        index_elements=['id'],
        set_={
            "name": stmt_parent.excluded.name,
            "layout": stmt_parent.excluded.layout,
            "edhrec_rank": stmt_parent.excluded.edhrec_rank,
            "rarity": stmt_parent.excluded.rarity,
            "legalities": stmt_parent.excluded.legalities
        }
    )
    session.execute(stmt_parent)
    
    # B. Generate Embeddings
    embeddings = model.encode(batch_texts, convert_to_tensor=False).tolist()
    
    # C. Delete old faces for these cards (to handle updates)
    parent_ids = [p['id'] for p in batch_parents]
    session.execute(delete(CardFace).where(CardFace.card_id.in_(parent_ids)))
    
    # D. Insert New Faces
    db_faces = [
        prepare_card_face(cid, fdata, emb) 
        for (cid, fdata), emb in zip(batch_faces_data, embeddings)
    ]
    session.execute(insert(CardFace).values(db_faces))

def ingest_data_diff(new_path: Path, old_path: Optional[Path], scryfall_metadata: Dict[str, Any], model: Any = None, trigger_type: str = "scheduled"):
    """
    Smart ingestion that compares new data against old data.
    1. Identifies Added, Modified, and Deleted cards.
    2. Updates DB accordingly.
    """
    logger.info("Starting smart database ingestion...")
    session = SessionLocal()
    
    # Create Ingestion Log
    log_entry = IngestionLog(
        status="started",
        schema_version=DB_SCHEMA_VERSION,
        trigger_type=trigger_type
    )
    session.add(log_entry)
    session.commit()
    log_id = log_entry.id

    if model is None:
        logger.info("Loading ML model for embeddings...")
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
    
    try:
        # 1. Load Old Data Map
        old_cards_map = {}
        if old_path and old_path.exists():
            old_cards_map = load_existing_cards_map(old_path)
        
        stats = {
            "added": 0,
            "modified": 0,
            "deleted": 0,
            "skipped": 0,
            "unchanged": 0
        }
        
        # 2. Stream New Data and Process Added/Modified
        batch_to_process = []
        
        with new_path.open("rb") as f:
            cards_stream = ijson.items(f, "item")
            
            for card in cards_stream:
                if should_skip_card(card):
                    stats["skipped"] += 1
                    continue
                
                card_id = card.get("id")
                existing_card = old_cards_map.pop(card_id, None)
                
                is_update_needed = False
                
                if existing_card is None:
                    # New Card
                    stats["added"] += 1
                    is_update_needed = True
                else:
                    # Existing Card - Check for changes
                    new_normalized = normalize_card_data(card)
                    if new_normalized != existing_card:
                        stats["modified"] += 1
                        is_update_needed = True
                    else:
                        stats["unchanged"] += 1
                
                if is_update_needed:
                    batch_to_process.append(card)
                    
                    if len(batch_to_process) >= BATCH_SIZE:
                        ingest_batch(session, model, batch_to_process)
                        session.commit()
                        batch_to_process = []
                        logger.info(f"Processed batch. Stats: {stats}")

            # Process remaining Added/Modified
            if batch_to_process:
                ingest_batch(session, model, batch_to_process)
                session.commit()
                batch_to_process = []
        
        # 3. Process Deletions
        # Any ID remaining in old_cards_map is deleted
        deleted_ids = list(old_cards_map.keys())
        stats["deleted"] = len(deleted_ids)
        
        if deleted_ids:
            logger.info(f"Deleting {len(deleted_ids)} removed cards...")
            # Delete in chunks to avoid massive query
            chunk_size = 1000
            for i in range(0, len(deleted_ids), chunk_size):
                chunk = deleted_ids[i:i + chunk_size]
                session.execute(delete(Card).where(Card.id.in_(chunk)))
                session.commit()
        
        # 4. Update Metadata and Log
        sys_meta = SystemMetadata(
            key="scryfall_data",
            data_updated_at=scryfall_metadata.get("updated_at"),
            last_ingestion=datetime.utcnow(),
            schema_version=DB_SCHEMA_VERSION
        )
        session.merge(sys_meta)
        
        log_entry = session.get(IngestionLog, log_id)
        if log_entry:
            log_entry.status = "success"
            log_entry.completed_at = datetime.utcnow()
            log_entry.records_processed = stats["added"] + stats["modified"] + stats["unchanged"]
            log_entry.records_skipped = stats["skipped"]
            # We can log detailed stats in error_message or a new field if we wanted, 
            # but for now standard fields. 
            # Maybe append stats to error_message field (used as notes)?
            log_entry.error_message = json.dumps(stats)
            
        session.commit()
        logger.info(f"Ingestion complete. Stats: {stats}")
        
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        session.rollback()
        
        # Update Log Failure
        try:
            with SessionLocal() as err_session:
                log_entry = err_session.get(IngestionLog, log_id)
                if log_entry:
                    log_entry.status = "failed"
                    log_entry.completed_at = datetime.utcnow()
                    log_entry.error_message = str(e)
                err_session.commit()
        except Exception as log_err:
            logger.error(f"Failed to write error log: {log_err}")
            
        raise
    finally:
        session.close()

def parse_version(version_str: str) -> tuple:
    """Helper to parse version string '1.0.2' to tuple (1, 0, 2) for comparison."""
    if not version_str:
        return (0, 0, 0)
    try:
        return tuple(map(int, version_str.split(".")))
    except ValueError:
        return (0, 0, 0)

def update_scryfall_data(force: bool = False, model: Any = None) -> bool:
    """
    Main entry point:
    1. Fetch Remote Metadata (R).
    2. Check Local File Metadata (L).
    3. Check DB Metadata (D).
    4. Decide actions:
       - If R > L: Download to Temp.
       - Ingest (Diff Temp vs L/Current).
       - On Success: Move Temp to Current.
    """
    setup_loggers()
    ensure_data_dir()
    init_db()
    
    # 1. Check Metadata
    try:
        remote_meta = fetch_bulk_metadata()
        remote_updated_at = remote_meta.get("updated_at")
    except Exception as e:
        logger.error(f"Failed to fetch remote metadata: {e}")
        if force:
            remote_meta = None
            remote_updated_at = None
        else:
            return False

    # 2. Check Local File
    local_meta = load_local_metadata()
    local_updated_at = local_meta.get("updated_at") if local_meta else None
    file_exists = CARDS_JSON.exists()

    # 3. Check DB
    session = SessionLocal()
    db_updated_at = None
    db_schema_version = "0.0"
    db_is_empty = True
    try:
        db_meta = session.get(SystemMetadata, "scryfall_data")
        if db_meta:
            db_updated_at = db_meta.data_updated_at
            db_schema_version = db_meta.schema_version or "0.0"
        
        card_count = session.query(func.count(Card.id)).scalar()
        db_is_empty = (card_count == 0)
    except Exception as e:
        logger.warning(f"DB check failed: {e}")
    finally:
        session.close()

    logger.info(f"Status: Remote={remote_updated_at}, Local={local_updated_at}, DB={db_updated_at}")

    trigger_type = "scheduled"
    if force:
        trigger_type = "force"
    
    # Decision Logic
    
    # A. Download Logic
    download_needed = False
    if force:
        download_needed = True
    elif not file_exists or not local_updated_at:
        download_needed = True
    elif remote_updated_at and remote_updated_at != local_updated_at:
        download_needed = True
        
    ingestion_source = CARDS_JSON
    
    if download_needed and remote_meta:
        try:
            download_uri = remote_meta["download_uri"]
            # Download to TEMP file first
            download_bulk_file(download_uri, TEMP_CARDS_JSON)
            ingestion_source = TEMP_CARDS_JSON
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False
    else:
        # No download needed, use existing file if exists
        if not CARDS_JSON.exists():
            logger.error("No local data found and download skipped.")
            return False
        ingestion_source = CARDS_JSON

    # B. Ingestion Logic
    ingestion_needed = False
    
    # If we downloaded a new file, we definitely ingest
    if ingestion_source == TEMP_CARDS_JSON:
        ingestion_needed = True
    elif force:
        ingestion_needed = True
    elif parse_version(str(db_schema_version)) < parse_version(DB_SCHEMA_VERSION):
        logger.info("Schema change detected. Forcing ingestion.")
        ingestion_needed = True
        trigger_type = "schema_change"
    elif db_is_empty:
        ingestion_needed = True
    elif local_updated_at != db_updated_at:
        ingestion_needed = True
        
    if ingestion_needed:
        try:
            # Identify 'Old' file for comparison
            # If we downloaded to Temp, CARDS_JSON is 'Old'.
            # If we are using CARDS_JSON as source (re-ingest), we have no 'Old' to compare against 
            # (or rather, Old is same as New).
            # To force a full re-check in re-ingest scenario, we can pass old_path=CARDS_JSON 
            # and the diff logic handles "same file" by marking as unchanged unless modified?
            # Actually, if new_path == old_path, diff logic sees them as identical.
            # So to force re-ingest of CARDS_JSON, we should pass old_path=None.
            
            old_path_for_diff = None
            if ingestion_source == TEMP_CARDS_JSON:
                # Comparing New Temp vs Existing
                old_path_for_diff = CARDS_JSON
            else:
                # Re-ingesting existing file. 
                # If force=True, we might want to re-process everything.
                # If we pass old_path=CARDS_JSON, it will detect 0 changes.
                # So pass None to treat all as "Added" (Upsert).
                old_path_for_diff = None

            logger.info(f"Ingesting from {ingestion_source}...")
            ingest_data_diff(
                new_path=ingestion_source,
                old_path=old_path_for_diff,
                scryfall_metadata=remote_meta if remote_meta else (local_meta or {}),
                model=model,
                trigger_type=trigger_type
            )
            
            # On Success:
            if ingestion_source == TEMP_CARDS_JSON:
                logger.info("Ingestion successful. Promoting temp file to active file.")
                shutil.move(str(TEMP_CARDS_JSON), str(CARDS_JSON))
                if remote_meta:
                    save_local_metadata(remote_meta)
                    
            return True
            
        except Exception as e:
            logger.error(f"Update process failed: {e}")
            # Clean up temp file if it exists
            if TEMP_CARDS_JSON.exists():
                TEMP_CARDS_JSON.unlink()
            return False
    
    logger.info("System is up to date.")
    return False

if __name__ == "__main__":
    update_scryfall_data(force=True)
