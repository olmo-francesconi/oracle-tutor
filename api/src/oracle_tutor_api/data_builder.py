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

from .config import CARDS_JSON, DATA_DIR
from .database import SessionLocal, engine
from .models import Base, Card, CardFace, SystemMetadata
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
    
    with engine.begin() as conn:
        # Schema Migration Check
        if has_cards and not has_faces:
            logger.warning("Old schema detected (cards table exists but no card_faces). Dropping old tables to rebuild...")
            conn.execute(text("DROP TABLE IF EXISTS cards CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS system_metadata CASCADE"))
            
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

def ingest_data(json_path: Path, scryfall_metadata: Dict[str, Any]):
    """Read JSON, generate embeddings, and insert into DB."""
    
    logger.info("Starting database ingestion...")
    session = SessionLocal()

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
                last_ingestion=datetime.utcnow()
            )
            session.merge(sys_meta)
            session.commit()
                
            logger.info(f"Ingestion complete. Total cards: {count}")
            
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        session.rollback()
        raise
    finally:
        session.close()

def update_scryfall_data(force: bool = False) -> bool:
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
    try:
        db_meta = session.get(SystemMetadata, "scryfall_data")
        db_updated_at = db_meta.data_updated_at if db_meta else None
        
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

    logger.info(f"Metadata Status: Remote={remote_updated_at}, LocalFile={local_updated_at}, DB={db_updated_at}")

    # Decision Logic
    
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
    elif not db_updated_at:
        should_ingest = True
    elif db_is_empty:
        logger.info("Database tables exist but are empty. Forcing ingestion.")
        should_ingest = True
    elif local_updated_at != db_updated_at:
        should_ingest = True
        
    if should_ingest:
        logger.info(f"Ingesting data (Local: {local_updated_at} -> DB: {db_updated_at})...")
        ingest_data(CARDS_JSON, local_meta)
        return True
    else:
        logger.info("Database is up to date. No ingestion needed.")
        return False

if __name__ == "__main__":
    # Run manually
    update_scryfall_data(force=True)
