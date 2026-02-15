from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import ijson
import requests
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from ..core.config import CARDS_JSON, DATA_DIR, DB_SCHEMA_VERSION, ensure_data_dir, parse_version
from ..core.db_init import init_db
from ..core.database import SessionLocal, engine
from ..core.logging_config import setup_loggers
from ..core.models import Card, CardFace, IngestionLog, SystemMetadata

logger = logging.getLogger("oracle_tutor_api.data")

BULK_DATA_URL = "https://api.scryfall.com/bulk-data/oracle-cards"
BATCH_SIZE = 500

META_JSON = DATA_DIR / "scryfall_meta.json"
TEMP_CARDS_JSON = DATA_DIR / "scryfall-cards-temp.json"


# Removed local ensure_data_dir, now in core.config


def _validate_scryfall_download_url(download_url: str) -> None:
    """
    Defensive guardrail: ensure we only download from Scryfall over HTTPS.

    This reduces SSRF risk in case the upstream metadata response is ever tampered with.
    """
    parsed = urlparse(download_url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme != "https":
        raise ValueError(f"Refusing non-https download URL: {download_url}")
    # Scryfall's bulk files are commonly hosted on `data.scryfall.io`, and may also be served
    # from other subdomains. Allow both `scryfall.com` and `scryfall.io` domains/subdomains.
    allowed_roots = ("scryfall.com", "scryfall.io")
    if not host or not any(host == root or host.endswith(f".{root}") for root in allowed_roots):
        raise ValueError(f"Refusing non-scryfall download host: {download_url}")


def fetch_bulk_metadata(url: str = BULK_DATA_URL) -> Dict[str, Any]:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def save_local_metadata(metadata: Dict[str, Any]) -> None:
    with META_JSON.open("w") as f:
        json.dump(metadata, f, indent=2)


def load_local_metadata() -> Optional[Dict[str, Any]]:
    if not META_JSON.exists():
        return None
    try:
        with META_JSON.open("r") as f:
            return json.load(f)
    except Exception:
        return None


def download_bulk_file(download_url: str, destination: Path = CARDS_JSON) -> None:
    logger.info("Downloading bulk data...")
    _validate_scryfall_download_url(download_url)
    with requests.get(download_url, stream=True, timeout=60, allow_redirects=True) as resp:
        resp.raise_for_status()
        # If we were redirected, ensure the final host is still allowed.
        _validate_scryfall_download_url(resp.url)
        with destination.open("wb") as out:
            for chunk in resp.iter_content(chunk_size=1_048_576):
                if chunk:
                    out.write(chunk)
    logger.info("Download complete.")


def should_skip_card(card: Dict[str, Any]) -> bool:
    """
    Return True for Scryfall records we don't want in the playable search corpus.

    Notes:
    - We intentionally ingest from Scryfall's `oracle-cards` bulk file, which includes
      several non-game-piece records.
    - A common culprit is "Theme Cards" used in Jumpstart-style products. These have
      `type_line == "Card"` and oracle text like "(Theme color: {R})".
    """

    if card.get("layout") in [
        "token",
        "double_faced_token",
        "art_series",
        "emblem",
        "planar",
        "scheme",
        "vanguard",
    ]:
        return True

    # Digital-only cards (Arena/Alchemy/etc).
    #
    # Prefer Scryfall's explicit `games` field when present: if it doesn't exist in paper,
    # we skip it. Our bundled `cards.json` may not include `games`, so we also keep a
    # conservative fallback heuristic below.
    games = card.get("games")
    if isinstance(games, list):
        # If Scryfall tells us the card isn't in paper, treat as digital-only.
        if "paper" not in games:
            # EXCEPTION: Some cards (like Vintage Masters reprints) may be the "representative"
            # object in Scryfall's oracle-cards file and listed as MTGO-only, but the card
            # itself exists in paper (and is legal/banned/restricted in paper formats).
            # We check if it has any paper legality status.
            legalities = card.get("legalities") or {}
            paper_formats = {
                "standard", "pioneer", "modern", "legacy", "vintage", "commander", "pauper"
            }
            # If it's legal, banned, or restricted in any paper format, we keep it.
            is_paper_legal = any(
                legalities.get(fmt) in ("legal", "restricted", "banned")
                for fmt in paper_formats
            )
            if not is_paper_legal:
                return True

    # Arena-rebalanced cards (prefixed "A-") should be excluded.
    name = (card.get("name") or "").strip()
    if name.startswith("A-"):
        return True
    for face in (card.get("card_faces") or []):
        face_name = (face.get("name") or "").strip()
        if face_name.startswith("A-"):
            return True

    # Fallback: digital-only cards commonly have an `arena_id` but no paper/market identifiers.
    # This is intentionally conservative to avoid excluding normal paper cards that also have
    # an Arena implementation (they typically have multiverse/mtgo/market IDs).
    if card.get("arena_id") is not None:
        multiverse_ids = card.get("multiverse_ids") or []
        has_paperish_ids = bool(multiverse_ids) or any(
            card.get(k) is not None for k in ("mtgo_id", "tcgplayer_id", "cardmarket_id")
        )
        if not has_paperish_ids:
            return True

    # Jumpstart theme/pack marker cards and similar non-game-piece records.
    # These present as `type_line: "Card"` (and for DFC variants, faces also use "Card").
    if (card.get("type_line") or "").strip() == "Card":
        return True

    faces = card.get("card_faces") or []
    for face in faces:
        if (face.get("type_line") or "").strip() == "Card":
            return True

    return False


def cleanup_unplayable_cards(session) -> dict:
    """
    Best-effort cleanup for unplayable records that may have been ingested previously.

    We remove:
    - Cards with layouts we always skip.
    - Cards that have at least one face with `type_line == "Card"` (Theme Cards).

    Returns lightweight stats for logging.
    """

    skip_layouts = [
        "token",
        "double_faced_token",
        "art_series",
        "emblem",
        "planar",
        "scheme",
        "vanguard",
    ]

    stats = {"deleted_cards_by_layout": 0, "deleted_cards_by_type_line_card": 0}

    # Delete by skipped layouts (delete faces explicitly for sqlite / non-cascading FKs).
    ids_by_layout = select(Card.id).where(Card.layout.in_(skip_layouts)).subquery()
    session.execute(delete(CardFace).where(CardFace.card_id.in_(select(ids_by_layout.c.id))))
    res = session.execute(delete(Card).where(Card.id.in_(select(ids_by_layout.c.id))))
    stats["deleted_cards_by_layout"] = int(getattr(res, "rowcount", 0) or 0)

    # Delete Theme Cards (type_line == "Card") (again: delete faces first for safety).
    ids_by_face_card = (
        select(CardFace.card_id).where(CardFace.type_line == "Card").distinct().subquery()
    )
    session.execute(delete(CardFace).where(CardFace.card_id.in_(select(ids_by_face_card.c.card_id))))
    res = session.execute(delete(Card).where(Card.id.in_(select(ids_by_face_card.c.card_id))))
    stats["deleted_cards_by_type_line_card"] = int(getattr(res, "rowcount", 0) or 0)

    return stats


def prepare_parent_card(card_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": card_data.get("id"),
        "name": card_data.get("name"),
        "layout": card_data.get("layout"),
        "cmc": card_data.get("cmc"),
        "edhrec_rank": card_data.get("edhrec_rank"),
        "rarity": card_data.get("rarity"),
        "legalities": card_data.get("legalities"),
    }


def prepare_card_face(card_id: str, face_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "card_id": card_id,
        "name": face_data.get("name"),
        "mana_cost": face_data.get("mana_cost"),
        "type_line": face_data.get("type_line"),
        "oracle_text": face_data.get("oracle_text"),
        "power": face_data.get("power"),
        "toughness": face_data.get("toughness"),
        "colors": face_data.get("colors"),
    }


def normalize_card_data(card: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {
        "id": card.get("id"),
        "name": card.get("name"),
        "layout": card.get("layout"),
        "cmc": card.get("cmc"),
        "edhrec_rank": card.get("edhrec_rank"),
        "rarity": card.get("rarity"),
        "legalities": card.get("legalities"),
    }

    faces = card.get("card_faces") or [card]
    normalized_faces: List[Dict[str, Any]] = []
    for face in faces:
        normalized_faces.append(
            {
                "name": face.get("name"),
                "mana_cost": face.get("mana_cost"),
                "type_line": face.get("type_line"),
                "oracle_text": face.get("oracle_text"),
                "power": face.get("power"),
                "toughness": face.get("toughness"),
                "colors": face.get("colors"),
            }
        )

    normalized["faces"] = normalized_faces
    return normalized


def load_existing_cards_map(file_path: Path) -> Dict[str, Dict[str, Any]]:
    if not file_path.exists():
        return {}

    logger.info("Loading existing data for diff-ingest...")
    try:
        with file_path.open("r") as f:
            data = json.load(f)
        out: Dict[str, Dict[str, Any]] = {}
        for card in data:
            if not should_skip_card(card):
                out[card.get("id")] = normalize_card_data(card)
        logger.info("Loaded %d existing cards.", len(out))
        return out
    except Exception as e:
        logger.warning("Failed to load existing file (%s). Treating as empty.", e)
        return {}


def ingest_batch(session, batch_cards: List[Dict[str, Any]]) -> None:
    if not batch_cards:
        return

    parents: List[Dict[str, Any]] = []
    faces_to_insert: List[Dict[str, Any]] = []

    for card in batch_cards:
        card_id = card.get("id")
        if not isinstance(card_id, str) or not card_id:
            # Defensive guard: Scryfall records should always have an id, but skip if malformed.
            continue
        parents.append(prepare_parent_card(card))
        faces = card.get("card_faces") or [card]
        for face in faces:
            faces_to_insert.append(prepare_card_face(card_id, face))

    # Upsert parents (Postgres only). For other DBs, do a slower path.
    if engine.dialect.name == "postgresql":
        stmt = insert(Card).values(parents)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "name": stmt.excluded.name,
                "layout": stmt.excluded.layout,
                "cmc": stmt.excluded.cmc,
                "edhrec_rank": stmt.excluded.edhrec_rank,
                "rarity": stmt.excluded.rarity,
                "legalities": stmt.excluded.legalities,
            },
        )
        session.execute(stmt)
    else:
        for p in parents:
            session.merge(Card(**p))

    parent_ids = [p["id"] for p in parents]
    session.execute(delete(CardFace).where(CardFace.card_id.in_(parent_ids)))

    if faces_to_insert:
        if engine.dialect.name == "postgresql":
            session.execute(insert(CardFace).values(faces_to_insert))
        else:
            session.bulk_insert_mappings(CardFace, faces_to_insert)


def ingest_data_diff(
    new_path: Path,
    old_path: Optional[Path],
    scryfall_metadata: Dict[str, Any],
    *,
    trigger_type: str = "scheduled",
) -> None:
    logger.info("Starting smart database ingestion...")
    session = SessionLocal()

    log_entry = IngestionLog(status="started", schema_version=DB_SCHEMA_VERSION, trigger_type=trigger_type)
    session.add(log_entry)
    session.commit()
    log_id = log_entry.id

    try:
        # Clean up known-unplayable records that might have been ingested historically.
        cleanup_stats = cleanup_unplayable_cards(session)
        if cleanup_stats["deleted_cards_by_layout"] or cleanup_stats["deleted_cards_by_type_line_card"]:
            logger.info("Cleanup removed unplayables: %s", cleanup_stats)
            session.commit()

        old_cards_map: Dict[str, Dict[str, Any]] = {}
        if old_path and old_path.exists():
            old_cards_map = load_existing_cards_map(old_path)

        stats = {"added": 0, "modified": 0, "deleted": 0, "skipped": 0, "unchanged": 0}

        batch: List[Dict[str, Any]] = []
        with new_path.open("rb") as f:
            stream = ijson.items(f, "item")
            for card in stream:
                if should_skip_card(card):
                    stats["skipped"] += 1
                    continue

                card_id = card.get("id")
                existing = old_cards_map.pop(card_id, None)

                update_needed = False
                if existing is None:
                    stats["added"] += 1
                    update_needed = True
                else:
                    new_norm = normalize_card_data(card)
                    if new_norm != existing:
                        stats["modified"] += 1
                        update_needed = True
                    else:
                        stats["unchanged"] += 1

                if update_needed:
                    batch.append(card)
                    if len(batch) >= BATCH_SIZE:
                        ingest_batch(session, batch)
                        session.commit()
                        batch = []
                        logger.info("Processed batch. Stats: %s", stats)

        if batch:
            ingest_batch(session, batch)
            session.commit()

        deleted_ids = list(old_cards_map.keys())
        stats["deleted"] = len(deleted_ids)
        if deleted_ids:
            logger.info("Deleting %d removed cards...", len(deleted_ids))
            chunk_size = 1000
            for i in range(0, len(deleted_ids), chunk_size):
                session.execute(delete(Card).where(Card.id.in_(deleted_ids[i : i + chunk_size])))
                session.commit()

        sys_meta = SystemMetadata(
            key="scryfall_data",
            data_updated_at=scryfall_metadata.get("updated_at") or "",
            last_ingestion=datetime.utcnow(),
            schema_version=DB_SCHEMA_VERSION,
        )
        session.merge(sys_meta)

        log_entry = session.get(IngestionLog, log_id)
        if log_entry:
            log_entry.status = "success"
            log_entry.completed_at = datetime.utcnow()
            log_entry.records_processed = stats["added"] + stats["modified"] + stats["unchanged"]
            log_entry.records_skipped = stats["skipped"]
            log_entry.error_message = json.dumps(stats)

        session.commit()
        logger.info("Ingestion complete. Stats: %s", stats)
    except Exception as e:
        logger.error("Ingestion failed: %s", e, exc_info=True)
        session.rollback()
        try:
            with SessionLocal() as err_session:
                log_entry = err_session.get(IngestionLog, log_id)
                if log_entry:
                    log_entry.status = "failed"
                    log_entry.completed_at = datetime.utcnow()
                    log_entry.error_message = str(e)
                err_session.commit()
        except Exception:
            logger.exception("Failed to write ingestion failure log.")
        raise
    finally:
        session.close()


def update_scryfall_data(
    *,
    force: bool = False,
    trigger_type: str | None = None,
    strict: bool = False,
) -> bool:
    """
    Download Scryfall oracle bulk file if needed and ingest into DB using diff-ingest.

    Returns True if ingestion ran, False if already up-to-date or download failed.
    """
    setup_loggers()
    ensure_data_dir()
    init_db()

    remote_meta: Dict[str, Any] | None = None
    remote_updated_at: str | None = None
    try:
        remote_meta = fetch_bulk_metadata()
        remote_updated_at = remote_meta.get("updated_at")
    except Exception as e:
        logger.error("Failed to fetch remote metadata: %s", e)
        if strict:
            raise
        if not force:
            return False

    local_meta = load_local_metadata()
    local_updated_at = local_meta.get("updated_at") if local_meta else None
    file_exists = CARDS_JSON.exists()

    # DB metadata check
    session = SessionLocal()
    db_updated_at: str | None = None
    db_schema_version = "0.0"
    db_is_empty = True
    try:
        db_meta = session.get(SystemMetadata, "scryfall_data")
        if db_meta:
            db_updated_at = db_meta.data_updated_at
            db_schema_version = db_meta.schema_version or "0.0"

        card_count = session.query(func.count(Card.id)).scalar()
        db_is_empty = (card_count == 0)
    finally:
        session.close()

    logger.info("Status: Remote=%s, Local=%s, DB=%s", remote_updated_at, local_updated_at, db_updated_at)

    effective_trigger = trigger_type or ("force" if force else "scheduled")

    schema_needs_ingest = parse_version(str(db_schema_version)) < parse_version(DB_SCHEMA_VERSION)

    # Stateless optimization:
    # If the DB already reflects the latest remote version, we can skip downloading the JSON
    # even if the container has no persisted /app/data directory.
    if (
        (not force)
        and (not schema_needs_ingest)
        and (not db_is_empty)
        and remote_updated_at
        and (db_updated_at == remote_updated_at)
    ):
        logger.info(
            "DB already matches remote metadata (%s); skipping download/ingestion.",
            remote_updated_at,
        )
        return False

    # Download decision
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
            download_bulk_file(remote_meta["download_uri"], TEMP_CARDS_JSON)
            ingestion_source = TEMP_CARDS_JSON
        except Exception as e:
            logger.error("Download failed: %s", e)
            if strict:
                raise
            return False
    else:
        if not CARDS_JSON.exists():
            logger.error("No local data found and download skipped.")
            if strict:
                raise RuntimeError("No local cards.json and remote download was unavailable/skipped.")
            return False

    # Ingestion decision
    ingestion_needed = False
    if ingestion_source == TEMP_CARDS_JSON:
        ingestion_needed = True
    elif force:
        ingestion_needed = True
    elif schema_needs_ingest:
        logger.info("Schema change detected. Forcing ingestion.")
        ingestion_needed = True
        effective_trigger = "schema_change"
    elif db_is_empty:
        ingestion_needed = True
    else:
        target_updated_at = remote_updated_at or local_updated_at
        if target_updated_at is not None and target_updated_at != db_updated_at:
            ingestion_needed = True

    if not ingestion_needed:
        logger.info("System is up to date.")
        return False

    try:
        old_path_for_diff: Optional[Path]
        if ingestion_source == TEMP_CARDS_JSON:
            old_path_for_diff = CARDS_JSON
        else:
            # Treat as full re-process when re-ingesting existing file.
            old_path_for_diff = None

        ingest_data_diff(
            new_path=ingestion_source,
            old_path=old_path_for_diff,
            scryfall_metadata=remote_meta if remote_meta else (local_meta or {}),
            trigger_type=effective_trigger,
        )

        if ingestion_source == TEMP_CARDS_JSON:
            logger.info("Promoting temp file to active file.")
            shutil.move(str(TEMP_CARDS_JSON), str(CARDS_JSON))
            if remote_meta:
                save_local_metadata(remote_meta)

        return True
    except Exception as e:
        logger.error("Update process failed: %s", e, exc_info=True)
        if strict:
            raise
        if TEMP_CARDS_JSON.exists():
            try:
                TEMP_CARDS_JSON.unlink()
            except Exception:
                logger.warning("Failed to cleanup temp cards file.")
        return False


