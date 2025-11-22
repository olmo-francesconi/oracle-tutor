import logging
import ijson
import re
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

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
    logger.info(f"Downloading bulk data from {download_url}...")
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
    
    log_cols = [c['name'] for c in inspector.get_columns("ingestion_logs")] if has_logs else []
    has_skipped_col = "records_skipped" in log_cols
    
    with engine.begin() as conn:
        # Schema Migration Check
        if (has_cards and not has_faces) or (has_sys_meta and not has_schema_version) or (has_logs and not has_skipped_col):
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

def ingest_data(json_path: Path, scryfall_metadata: Dict[str, Any], model: Any = None, trigger_type: str = "scheduled"):
    """Read JSON, generate embeddings, and insert into DB."""
    
    logger.info("Starting database ingestion...")
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
        logger.info("Loading ML model for embeddings (this may take a moment)...")
        # Load a small, fast model for semantic search
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
    
    try:
        with json_path.open("rb") as f:
            # Stream the JSON file
            cards = ijson.items(f, "item")
            
            batch_parents = []
            batch_faces_data = []
            batch_texts = []
            count = 0
            skipped_count = 0
            
            for card in cards:
                # Skip tokens, art cards, and other non-playable types
                if card.get("layout") in [
                    "token", 
                    "double_faced_token", 
                    "art_series", 
                    "emblem", 
                    "planar", 
                    "scheme", 
                    "vanguard"
                ]:
                    skipped_count += 1
                    continue

                # 1. Prepare Parent Card
                batch_parents.append(prepare_parent_card(card))
                
                # 2. Identify Faces
                faces = card.get("card_faces")
                if not faces:
                    # Single face card: the card object itself is the face
                    faces = [card]
                
                for face in faces:
                    # Prepare text for embedding: Oracle Text only
                    oracle_text = face.get("oracle_text", "") or ""
                    face_name = face.get("name", "")
                    expanded_text = expand_symbols(oracle_text, card_name=face_name)
                    
                    text_to_embed = f"{expanded_text}"
                    
                    batch_texts.append(text_to_embed)
                    batch_faces_data.append((card.get("id"), face))
                
                # 3. Process Batch
                # We trigger based on number of faces or just periodically.
                # Since batch_parents and batch_faces grow at different rates, 
                # we can trigger on batch_parents size or text size.
                if len(batch_texts) >= BATCH_SIZE:
                    # A. Upsert Parents
                    stmt_parent = insert(Card).values(batch_parents)
                    stmt_parent = stmt_parent.on_conflict_do_update(
                        index_elements=['id'],
                        set_={
                            "name": stmt_parent.excluded.name,
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
                    
                    session.commit()
                    
                    count += len(batch_parents)
                    logger.info(f"Processed {count} cards...")
                    
                    # Reset batches
                    batch_parents = []
                    batch_faces_data = []
                    batch_texts = []

            # Process remaining items
            if batch_parents:
                # A. Upsert Parents
                stmt_parent = insert(Card).values(batch_parents)
                stmt_parent = stmt_parent.on_conflict_do_update(
                    index_elements=['id'],
                    set_={
                        "name": stmt_parent.excluded.name,
                        "edhrec_rank": stmt_parent.excluded.edhrec_rank,
                        "rarity": stmt_parent.excluded.rarity,
                        "legalities": stmt_parent.excluded.legalities
                    }
                )
                session.execute(stmt_parent)
                
                # B. Generate Embeddings
                embeddings = model.encode(batch_texts, convert_to_tensor=False).tolist()
                
                # C. Delete old faces
                parent_ids = [p['id'] for p in batch_parents]
                session.execute(delete(CardFace).where(CardFace.card_id.in_(parent_ids)))
                
                # D. Insert New Faces
                db_faces = [
                    prepare_card_face(cid, fdata, emb) 
                    for (cid, fdata), emb in zip(batch_faces_data, embeddings)
                ]
                session.execute(insert(CardFace).values(db_faces))
                
                session.commit()
                count += len(batch_parents)
            
            # Update System Metadata
            sys_meta = SystemMetadata(
                key="scryfall_data",
                data_updated_at=scryfall_metadata.get("updated_at"),
                last_ingestion=datetime.utcnow(),
                schema_version=DB_SCHEMA_VERSION
            )
            session.merge(sys_meta)
            
            # Update Log Success
            log_entry = session.get(IngestionLog, log_id)
            if log_entry:
                log_entry.status = "success"
                log_entry.completed_at = datetime.utcnow()
                log_entry.records_processed = count
                log_entry.records_skipped = skipped_count
            
            session.commit()
                
            logger.info(f"Ingestion complete. Total cards: {count}, Skipped: {skipped_count}")
            
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        session.rollback()
        
        # Update Log Failure (New session for safety)
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
       - If R > L or L missing: Download File, Update L.
       - If L > D or D missing: Ingest File, Update D.
    """
    setup_loggers()
    ensure_data_dir()
    
    # Always ensure DB is initialized (tables exist)
    init_db()
    
    # 1. Check Metadata
    try:
        remote_meta = fetch_bulk_metadata()
        remote_updated_at = remote_meta.get("updated_at")
    except Exception as e:
        logger.error(f"Failed to fetch remote metadata: {e}")
        if force:
            logger.warning("Force update requested but remote metadata failed. Cannot download. Checking local files...")
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
    db_is_empty = False
    db_schema_version = "0.0"
    try:
        db_meta = session.get(SystemMetadata, "scryfall_data")
        db_updated_at = db_meta.data_updated_at if db_meta else None
        db_schema_version = db_meta.schema_version if db_meta and db_meta.schema_version else "0.0"
        
        # Safety check: Is the database actually populated?
        card_count = session.query(func.count(Card.id)).scalar()
        face_count = session.query(func.count(CardFace.id)).scalar()
        db_is_empty = (card_count == 0) or (face_count == 0)
    except Exception as e:
        logger.warning(f"Could not read system metadata from DB: {e}")
        db_updated_at = None
        db_is_empty = True
    finally:
        session.close()

    logger.info(f"Metadata Status: Remote={remote_updated_at}, LocalFile={local_updated_at}, DB={db_updated_at}, SchemaVer={db_schema_version}")

    # Decision Logic
    trigger_type = "scheduled"
    if force:
        trigger_type = "force"
    
    # Should we download?
    should_download = False
    if remote_updated_at:
        if force:
            should_download = True
        elif not file_exists or not local_updated_at:
            should_download = True
        elif remote_updated_at != local_updated_at:
            should_download = True
    
    if should_download:
        try:
            download_uri = remote_meta["download_uri"]
            download_bulk_file(download_uri)
            save_local_metadata(remote_meta)
            # Update our local variable after download
            local_meta = remote_meta
            local_updated_at = remote_updated_at
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False
    
    # Should we ingest?
    if not CARDS_JSON.exists() or not local_meta:
        logger.error("No local data available to ingest.")
        return False

    should_ingest = False
    if force:
        should_ingest = True
    elif parse_version(str(db_schema_version)) < parse_version(DB_SCHEMA_VERSION):
        logger.info(f"Database schema version ({db_schema_version}) is older than current code version ({DB_SCHEMA_VERSION}). Forcing re-ingestion.")
        should_ingest = True
        trigger_type = "schema_change"
    elif not db_updated_at:
        should_ingest = True
    elif db_is_empty:
        logger.info("Database tables exist but are empty. Forcing ingestion.")
        should_ingest = True
    elif local_updated_at != db_updated_at:
        should_ingest = True
        
    if should_ingest:
        logger.info(f"Ingesting data (Local: {local_updated_at} -> DB: {db_updated_at})...")
        ingest_data(CARDS_JSON, local_meta, model=model, trigger_type=trigger_type)
        return True
    else:
        logger.info("Database is up to date. No ingestion needed.")
        return False

if __name__ == "__main__":
    # Run manually
    update_scryfall_data(force=True)
