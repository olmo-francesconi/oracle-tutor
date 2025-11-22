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

def expand_symbols(text: str, card_name: str = None) -> str:
    """
    Expand MTG symbols like {T}, {W}, {2/W} into semantic text.
    """
    if not text:
        return ""
    
    # Replace card name with "this card"
    if card_name:
        text = text.replace(card_name, "this card")
        # Handle legendary short names (e.g. "Thalia, Guardian of Thraben" -> "Thalia")
        # Many legendary cards are referred to by their full name first, then short name.
        if "," in card_name:
            short_name = card_name.split(",")[0].strip()
            if len(short_name) > 2: # Basic safety check
                text = text.replace(short_name, "this card")

    # Remove remainder text in parenthesis (usually reminder text)
    text = re.sub(r'\([^)]*\)', '', text)

    # Ensure lines end with punctuation and join them
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    text = ""
    for line in lines:
        if not line.endswith(('.', '!', '?')):
            line += '.'
        text += line + " "

    # 1. Pre-calculate simple mappings for the loop
    # We use the same map structure but inverted for easy lookup in the loop if needed,
    # or just rely on the main symbol_map later. However, for "three white mana"
    # we need to know what "{W}" means in a singular noun form.
    
    # Base definitions for countable symbols
    countable_map = {
        "{W}": "white mana",
        "{U}": "blue mana",
        "{B}": "black mana",
        "{R}": "red mana",
        "{G}": "green mana",
        "{C}": "colorless mana",
        "{S}": "snow mana",
        "{E}": "energy counter",
        "{TK}": "ticket counter",
        "{P}": "modal budget pawprint",
        "{T}": "tap this permanent", # special plural handling needed? usually just "tap this permanent" repeated is weird, but we'll handle count
        "{Q}": "untap this permanent",
    }

    # Special handling for Phyrexians to match "N times one X or 2 life"
    phyrexian_bases = {
        "{X}": "X generic mana",
        "{W/P}": "one white mana or two life",
        "{U/P}": "one blue mana or two life",
        "{B/P}": "one black mana or two life",
        "{R/P}": "one red mana or two life",
        "{G/P}": "one green mana or two life",
        "{B/G/P}": "one black mana, one green mana, or 2 life",
        "{B/R/P}": "one black mana, one red mana, or 2 life",
        "{G/U/P}": "one green mana, one blue mana, or 2 life",
        "{G/W/P}": "one green mana, one white mana, or 2 life",
        "{R/G/P}": "one red mana, one green mana, or 2 life",
        "{R/W/P}": "one red mana, one white mana, or 2 life",
        "{U/B/P}": "one blue mana, one black mana, or 2 life",
        "{U/R/P}": "one blue mana, one red mana, or 2 life",
        "{W/B/P}": "one white mana, one black mana, or 2 life",
        "{W/U/P}": "one white mana, one blue mana, or 2 life",
        
        # Hybrids also follow "N times..." pattern for repetitions
        "{W/U}": "one white or blue mana",
        "{W/B}": "one white or black mana",
        "{B/R}": "one black or red mana",
        "{B/G}": "one black or green mana",
        "{U/B}": "one blue or black mana",
        "{U/R}": "one blue or red mana",
        "{R/G}": "one red or green mana",
        "{R/W}": "one red or white mana",
        "{G/W}": "one green or white mana",
        "{G/U}": "one green or blue mana",
        "{C/W}": "one colorless mana or one white mana",
        "{C/U}": "one colorless mana or one blue mana",
        "{C/B}": "one colorless mana or one black mana",
        "{C/R}": "one colorless mana or one red mana",
        "{C/G}": "one colorless mana or one green mana",
        "{2/W}": "two generic mana or one white mana",
        "{2/U}": "two generic mana or one blue mana",
        "{2/B}": "two generic mana or one black mana",
        "{2/R}": "two generic mana or one red mana",
        "{2/G}": "two generic mana or one green mana",
    }
    
    # Also update countable_map to REMOVE hybrids so they fall through to phyrexian_bases logic
    # (phyrexian_bases logic is "N times BASE")
    
    # Helper to convert number to word
    def num_to_word(n):
        words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
        if 0 <= n <= 10:
            return words[n]
        return str(n)

    # Regex to find sequences of identical symbols: e.g. {W}{W}{W}
    # Captures the inner content of the first symbol, then checks for repeats
    
    # 2. Programmatic Replacement of Repeats
    def replace_repeats(match):
        symbol = match.group(1) # e.g. {W}
        full_match = match.group(0)
        count = full_match.count(symbol)
        
        if count == 1:
            return full_match # Let the standard map handle single instances later
            
        # Handle Phyrexians
        if symbol in phyrexian_bases:
            base_text = phyrexian_bases[symbol]
            return f" {num_to_word(count)} times {base_text} "
            
        # Handle Countables (Mana, Counters)
        if symbol in countable_map:
            base_text = countable_map[symbol]
            
            # Pluralize if needed
            if count > 1:
                if "counter" in base_text and not base_text.endswith("s"):
                    base_text += "s"
                # Special case: actions like "tap this permanent" don't pluralize well naturally
                # as "tap this permanents", but "tap this permanent twice" is better.
                # However, for 3+ taps "tap this permanent three times" is consistent.
                if symbol == "{T}":
                    if count == 2:
                        return " tap this permanent twice "
                    return f" tap this permanent {num_to_word(count)} times "
                if symbol == "{Q}":
                    if count == 2:
                        return " untap this permanent twice "
                    return f" untap this permanent {num_to_word(count)} times "
                    
            return f" {num_to_word(count)} {base_text} "

        # Fallback for unknown repeats: just space them out
        return " ".join([symbol] * count)

    # This regex matches a symbol pattern like {X} and then greedily matches
    # immediate subsequent identical patterns.
    # \1 backreferences the entire first group (e.g., {W})
    text = re.sub(r'(\{[^}]+\})(\1+)', replace_repeats, text)

    symbol_map = {
        # Actions / Counters / Special
        "{T}": "tap this permanent",
        "{Q}": "untap this permanent",
        "{E}": "an energy counter",
        "{P}": "modal budget pawprint",
        "{PW}": "planeswalker",
        "{CHAOS}": "chaos",
        "{A}": "acorn",
        "{TK}": "a ticket counter",
        "{X}": "X generic mana",
        "{0}": "zero mana",
        "{H}": "one colored mana or two life",
        "{S}": "one snow",

        # Basic Mana
        "{W}": "one white mana",
        "{U}": "one blue mana",
        "{B}": "one black mana",
        "{R}": "one red mana",
        "{G}": "one green mana",
        "{C}": "one colorless mana",

        # Numeric
        "{1}": "one generic mana",
        "{2}": "two generic mana",
        "{3}": "three generic mana",
        "{4}": "four generic mana",
        "{5}": "five generic mana",
        "{6}": "six generic mana",
        "{7}": "seven generic mana",
        "{8}": "eight generic mana",
        "{9}": "nine generic mana",
        "{10}": "ten generic mana",
        "{11}": "eleven generic mana",
        "{12}": "twelve generic mana",
        "{13}": "thirteen generic mana",
        "{14}": "fourteen generic mana",
        "{15}": "fifteen generic mana",
        "{16}": "sixteen generic mana",
        "{17}": "seventeen generic mana",
        "{18}": "eighteen generic mana",
        "{19}": "nineteen generic mana",
        "{20}": "twenty generic mana",

        # Hybrid
        "{W/U}": "one white or blue mana",
        "{W/B}": "one white or black mana",
        "{B/R}": "one black or red mana",
        "{B/G}": "one black or green mana",
        "{U/B}": "one blue or black mana",
        "{U/R}": "one blue or red mana",
        "{R/G}": "one red or green mana",
        "{R/W}": "one red or white mana",
        "{G/W}": "one green or white mana",
        "{G/U}": "one green or blue mana",

        # Phyrexian Hybrid (Triples)
        "{B/G/P}": "one black mana, one green mana, or 2 life",
        "{B/R/P}": "one black mana, one red mana, or 2 life",
        "{G/U/P}": "one green mana, one blue mana, or 2 life",
        "{G/W/P}": "one green mana, one white mana, or 2 life",
        "{R/G/P}": "one red mana, one green mana, or 2 life",
        "{R/W/P}": "one red mana, one white mana, or 2 life",
        "{U/B/P}": "one blue mana, one black mana, or 2 life",
        "{U/R/P}": "one blue mana, one red mana, or 2 life",
        "{W/B/P}": "one white mana, one black mana, or 2 life",
        "{W/U/P}": "one white mana, one blue mana, or 2 life",

        # Colorless Hybrid
        "{C/W}": "one colorless mana or one white mana",
        "{C/U}": "one colorless mana or one blue mana",
        "{C/B}": "one colorless mana or one black mana",
        "{C/R}": "one colorless mana or one red mana",
        "{C/G}": "one colorless mana or one green mana",

        # 2/Color Hybrid
        "{2/W}": "two generic mana or one white mana",
        "{2/U}": "two generic mana or one blue mana",
        "{2/B}": "two generic mana or one black mana",
        "{2/R}": "two generic mana or one red mana",
        "{2/G}": "two generic mana or one green mana",

        # Phyrexian
        "{W/P}": "one white mana or two life",
        "{U/P}": "one blue mana or two life",
        "{B/P}": "one black mana or two life",
        "{R/P}": "one red mana or two life",
        "{G/P}": "one green mana or two life",
    }

    def replace_match(match):
        key = match.group(0)
        if key in symbol_map:
            return f" {symbol_map[key]} "
        
        # Fallback for other numeric values not in the specific list
        numeric_match = re.match(r'^\{(\d+)\}$', key)
        if numeric_match:
            return f" {numeric_match.group(1)} generic mana "
            
        return key

    text = re.sub(r'\{[a-zA-Z0-9/]+\}', replace_match, text)

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

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
