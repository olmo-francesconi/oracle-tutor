from __future__ import annotations

import json
import logging
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import ijson
import requests
from sqlalchemy import Table, bindparam, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from ..core.config import (
    API_BASE_URL,
    CARDS_JSON,
    DATA_DIR,
    DB_SCHEMA_VERSION,
    WORKER_REBUILD_PATH,
    WORKER_REBUILD_TIMEOUT_SECONDS,
    WORKER_TRIGGER_TOKEN,
    ensure_data_dir,
    parse_version,
)
from ..core.db_init import INIT_MODE_WORKER, init_db
from ..core.database import SessionLocal, engine
from ..core.logging_config import setup_loggers
from ..core.models import Card, CardFace, CardFaceSemanticEmbedding, CardRelationship, CardTagging, IngestionLog, SystemMetadata
from .fetch_tags import run_fetch_tags

logger = logging.getLogger("oracle_tutor_api.data")

BULK_DATA_URL = "https://api.scryfall.com/bulk-data/default-cards"
BATCH_SIZE = 500

META_JSON = DATA_DIR / "scryfall_meta.json"
TEMP_CARDS_JSON = DATA_DIR / "scryfall-cards-temp.json"


# Internal API trigger headers/contract
_WORKER_TRIGGER_HEADER = "X-Worker-Token"
_WORKER_SOURCE_HEADER = "X-Worker-Source"


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _trigger_tfidf_rebuild_request() -> None:
    if not API_BASE_URL:
        logger.info("Skipping TF-IDF rebuild trigger: ORACLE_TUTOR_API_BASE_URL not configured.")
        return
    if not WORKER_TRIGGER_TOKEN:
        logger.info("Skipping TF-IDF rebuild trigger: ORACLE_TUTOR_API_WORKER_TOKEN not configured.")
        return

    url = f"{API_BASE_URL}{WORKER_REBUILD_PATH}"
    logger.info(
        "Sending TF-IDF rebuild trigger to API. url=%s timeout_s=%.2f token_configured=%s",
        url,
        WORKER_REBUILD_TIMEOUT_SECONDS,
        bool(WORKER_TRIGGER_TOKEN),
    )
    headers = {
        _WORKER_TRIGGER_HEADER: WORKER_TRIGGER_TOKEN,
        _WORKER_SOURCE_HEADER: "worker",
    }
    try:
        resp = requests.post(url, headers=headers, timeout=WORKER_REBUILD_TIMEOUT_SECONDS)
        if resp.status_code >= 400:
            logger.warning(
                "TF-IDF rebuild trigger returned HTTP %s from %s. body=%s",
                resp.status_code,
                url,
                resp.text[:300],
            )
            return
        logger.info("TF-IDF rebuild trigger accepted by API (status=%s).", resp.status_code)
    except Exception as e:
        logger.warning("TF-IDF rebuild trigger failed (best-effort): %s", e)


def trigger_tfidf_rebuild_best_effort(*, async_call: bool = True) -> None:
    if async_call:
        logger.info("Scheduling async best-effort TF-IDF rebuild trigger.")
        # Non-daemon thread: for one-shot worker runs, this allows the process to wait
        # for the short-timeout request so trigger logs/attempt are not silently dropped.
        thread = threading.Thread(target=_trigger_tfidf_rebuild_request, daemon=False, name="tfidf-rebuild-trigger")
        thread.start()
        return
    logger.info("Running synchronous best-effort TF-IDF rebuild trigger.")
    _trigger_tfidf_rebuild_request()


def _delete_card_related_rows(session, card_ids: List[str]) -> None:
    if not card_ids:
        return

    chunk_size = 1000
    for i in range(0, len(card_ids), chunk_size):
        chunk = card_ids[i : i + chunk_size]
        face_ids = session.scalars(select(CardFace.id).where(CardFace.card_id.in_(chunk))).all()
        if face_ids:
            session.execute(delete(CardFaceSemanticEmbedding).where(CardFaceSemanticEmbedding.face_id.in_(face_ids)))
        session.execute(delete(CardRelationship).where(CardRelationship.card_id.in_(chunk)))
        session.execute(delete(CardTagging).where(CardTagging.card_id.in_(chunk)))
        session.execute(delete(CardFace).where(CardFace.card_id.in_(chunk)))


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

    # Delete by skipped layouts (delete dependents explicitly for sqlite / non-cascading FKs).
    ids_by_layout = session.scalars(select(Card.id).where(Card.layout.in_(skip_layouts))).all()
    _delete_card_related_rows(session, ids_by_layout)
    res = session.execute(delete(Card).where(Card.id.in_(ids_by_layout)))
    stats["deleted_cards_by_layout"] = int(getattr(res, "rowcount", 0) or len(ids_by_layout))

    # Delete Theme Cards (type_line == "Card") (again: delete faces first for safety).
    ids_by_face_card = session.scalars(
        select(CardFace.card_id).where(CardFace.type_line == "Card").distinct()
    ).all()
    _delete_card_related_rows(session, ids_by_face_card)
    res = session.execute(delete(Card).where(Card.id.in_(ids_by_face_card)))
    stats["deleted_cards_by_type_line_card"] = int(getattr(res, "rowcount", 0) or len(ids_by_face_card))

    return stats


def prepare_parent_card(card_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": card_data.get("id"),
        "name": card_data.get("name"),
        "scryfall_set": card_data.get("set"),
        "collector_number": card_data.get("collector_number"),
        "layout": card_data.get("layout"),
        "cmc": card_data.get("cmc"),
        "edhrec_rank": card_data.get("edhrec_rank"),
        "rarity": card_data.get("rarity"),
        "legalities": card_data.get("legalities"),
        "color_identity": card_data.get("color_identity"),
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
        "scryfall_set": card.get("set"),
        "collector_number": card.get("collector_number"),
        "layout": card.get("layout"),
        "cmc": card.get("cmc"),
        "edhrec_rank": card.get("edhrec_rank"),
        "rarity": card.get("rarity"),
        "legalities": card.get("legalities"),
        "color_identity": card.get("color_identity"),
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
                "scryfall_set": stmt.excluded.scryfall_set,
                "collector_number": stmt.excluded.collector_number,
                "layout": stmt.excluded.layout,
                "cmc": stmt.excluded.cmc,
                "edhrec_rank": stmt.excluded.edhrec_rank,
                "rarity": stmt.excluded.rarity,
                "legalities": stmt.excluded.legalities,
                "color_identity": stmt.excluded.color_identity,
            },
        )
        session.execute(stmt)
    else:
        for p in parents:
            session.merge(Card(**p))

    parent_ids = [p["id"] for p in parents]
    _delete_card_related_rows(session, parent_ids)

    if faces_to_insert:
        if engine.dialect.name == "postgresql":
            session.execute(insert(CardFace).values(faces_to_insert))
        else:
            session.bulk_insert_mappings(CardFace, faces_to_insert)


def select_best_printing(current: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compare two card objects (printings) and return the one we prefer to keep.
    Preference order:
    1. Paper over Digital (unless Digital is the only option).
    2. Oldest release date.
    3. Lowest collector number (tie-breaker).
    """
    # 1. Paper preference
    curr_games = current.get("games") or []
    cand_games = candidate.get("games") or []
    curr_is_paper = "paper" in curr_games
    cand_is_paper = "paper" in cand_games

    if curr_is_paper and not cand_is_paper:
        return current
    if cand_is_paper and not curr_is_paper:
        return candidate

    # 2. Release date (prefer older)
    curr_date = current.get("released_at") or "9999-99-99"
    cand_date = candidate.get("released_at") or "9999-99-99"

    if cand_date < curr_date:
        return candidate
    if curr_date < cand_date:
        return current

    # 3. Collector number (tie-breaker, prefer lower/lexicographically smaller)
    # This helps stabilize choice within the same set
    curr_cn = current.get("collector_number") or "zzzz"
    cand_cn = candidate.get("collector_number") or "zzzz"

    # Try integer comparison if possible, else string
    try:
        if int(cand_cn) < int(curr_cn):
            return candidate
        if int(curr_cn) < int(cand_cn):
            return current
    except ValueError:
        if cand_cn < curr_cn:
            return candidate
        if curr_cn < cand_cn:
            return current

    return current


def ingest_data_diff(
    new_path: Path,
    old_path: Optional[Path],
    scryfall_metadata: Dict[str, Any],
    *,
    trigger_type: str = "scheduled",
) -> None:
    logger.info("Starting smart database ingestion (with printing selection)...")
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

        # Load existing cards map (keyed by oracle_id for stability, or id if we want to track specific printings)
        # NOTE: Since we are now selecting printings dynamically, the "id" in our DB might change for the same card
        # if a better printing becomes available (unlikely for "oldest", but possible if we change logic).
        # For diffing, we should probably compare based on oracle_id to see if the *content* changed,
        # but our DB schema uses Scryfall UUID as primary key.
        #
        # Strategy:
        # 1. Read NEW file fully (it's big, but we need to reduce it).
        # 2. Build map of oracle_id -> best_printing_card_object.
        # 3. Compare this map against DB state.

        logger.info("Reading and reducing new bulk data...")
        best_printings: Dict[str, Dict[str, Any]] = {}
        stats = {"seen": 0, "kept": 0, "skipped": 0}

        with new_path.open("rb") as f:
            stream = ijson.items(f, "item")
            for card in stream:
                stats["seen"] += 1
                if should_skip_card(card):
                    stats["skipped"] += 1
                    continue

                oracle_id = card.get("oracle_id")
                if not oracle_id:
                    # Fallback for cards without oracle_id (rare, usually tokens/etc we skip anyway)
                    continue

                if oracle_id not in best_printings:
                    best_printings[oracle_id] = card
                else:
                    best_printings[oracle_id] = select_best_printing(best_printings[oracle_id], card)

        stats["kept"] = len(best_printings)
        logger.info("Reduction complete. Stats: %s", stats)

        # Now we have the list of cards we WANT to be in the DB.
        # We need to see what to add/update/delete.
        # Since we might be switching from one printing ID to another for the same oracle_id,
        # "modified" is tricky.
        #
        # Simplification:
        # We will iterate over our `best_printings` values.
        # For each card, we check if its specific UUID is in the DB.
        # If yes -> check for updates.
        # If no -> check if we have another card with same oracle_id?
        # Actually, our `load_existing_cards_map` loads by ID.
        #
        # Let's load existing IDs from DB to know what to delete.
        # (We can't easily use the old JSON file for diffing because we are changing the selection logic
        # on the fly, and the old JSON might be the raw file, not our reduced set).

        # Fetch all existing IDs from DB
        existing_ids = set(session.scalars(select(Card.id)).all())
        logger.info("Found %d existing cards in DB.", len(existing_ids))

        ingest_stats = {"added": 0, "modified": 0, "deleted": 0, "unchanged": 0}
        batch: List[Dict[str, Any]] = []

        # We need to handle the case where we swap printing A for printing B.
        # We should insert B and delete A.
        # Since we are iterating over the NEW set (B), we will insert B.
        # A will be left in `existing_ids` and deleted at the end.

        # Optimization: To detect "modified" (same ID, content changed), we need the old data.
        # But for now, `merge` (upsert) handles added/modified/unchanged safely for Postgres.
        # We just need to count them.

        for card in best_printings.values():
            card_id = card.get("id")
            if card_id in existing_ids:
                existing_ids.remove(card_id)
                # Ideally we'd check if content changed to inc 'modified' vs 'unchanged'
                # For now, we'll just count as "processed" or assume unchanged if we don't check.
                # Let's assume unchanged for stats unless we actually check.
                # (To do it right, we'd need to fetch the row or have the old map).
                ingest_stats["unchanged"] += 1 # Approximation
            else:
                ingest_stats["added"] += 1

            batch.append(card)
            if len(batch) >= BATCH_SIZE:
                ingest_batch(session, batch)
                session.commit()
                batch = []

        if batch:
            ingest_batch(session, batch)
            session.commit()

        # Remaining existing_ids are cards that are no longer the "best printing"
        # (or were removed entirely).
        ingest_stats["deleted"] = len(existing_ids)
        if existing_ids:
            logger.info("Deleting %d obsolete cards/printings...", len(existing_ids))
            chunk_size = 1000
            existing_ids_list = list(existing_ids)
            for i in range(0, len(existing_ids_list), chunk_size):
                chunk = existing_ids_list[i : i + chunk_size]
                _delete_card_related_rows(session, chunk)
                session.execute(delete(Card).where(Card.id.in_(chunk)))
                session.commit()

        sys_meta = SystemMetadata(
            key="scryfall_data",
            data_updated_at=scryfall_metadata.get("updated_at") or "",
            last_ingestion=_utcnow_naive(),
            schema_version=DB_SCHEMA_VERSION,
        )
        session.merge(sys_meta)

        log_entry = session.get(IngestionLog, log_id)
        if log_entry:
            log_entry.status = "success"
            log_entry.completed_at = _utcnow_naive()
            log_entry.records_processed = ingest_stats["added"] + ingest_stats["unchanged"] # + modified
            log_entry.records_skipped = stats["skipped"]
            log_entry.error_message = json.dumps(ingest_stats)

        session.commit()
        logger.info("Ingestion complete. Stats: %s", ingest_stats)
    except Exception as e:
        logger.error("Ingestion failed: %s", e, exc_info=True)
        session.rollback()
        try:
            with SessionLocal() as err_session:
                log_entry = err_session.get(IngestionLog, log_id)
                if log_entry:
                    log_entry.status = "failed"
                    log_entry.completed_at = _utcnow_naive()
                    log_entry.error_message = str(e)
                err_session.commit()
        except Exception:
            logger.exception("Failed to write ingestion failure log.")
        raise
    finally:
        session.close()


UNIQUENESS_THRESHOLD = 0.40
UNIQUENESS_POWER = 2.0
UNIQUENESS_BATCH_SIZE = 500


def compute_and_store_uniqueness_scores(session) -> None:
    """
    Compute a uniqueness score (0-100) for every card and write it to the DB.

    Algorithm:
      1. Build TF-IDF index from all card faces (reuses the API's index builder).
      2. For each face, sum sim^power for all above-threshold similarities
         (excluding same-card faces). This "redundancy" captures both depth
         and breadth of similar cards.
      3. Aggregate to card level (max across faces).
      4. Convert to uniqueness via log-scaled normalization:
           uniqueness = 100 * (1 - log(1+raw) / log(1+max_raw))
    """
    import time

    import numpy as np
    from ..api.tfidf_index import build_tfidf_index

    logger.info("Computing uniqueness scores (threshold=%.2f, power=%.1f)...", UNIQUENESS_THRESHOLD, UNIQUENESS_POWER)
    t0 = time.perf_counter()

    index = build_tfidf_index(session)
    n = len(index.face_ids)
    if n == 0:
        logger.warning("No faces found; skipping uniqueness computation.")
        return

    matrix = index.matrix_l2
    face_card_ids = index.face_card_ids

    card_face_map: Dict[str, List[int]] = {}
    for i, cid in enumerate(face_card_ids):
        card_face_map.setdefault(cid, []).append(i)

    face_redundancy = np.zeros(n, dtype=np.float64)

    for batch_start in range(0, n, UNIQUENESS_BATCH_SIZE):
        batch_end = min(batch_start + UNIQUENESS_BATCH_SIZE, n)
        batch = matrix[batch_start:batch_end]

        sims = batch @ matrix.T
        try:
            sims = np.asarray(sims.toarray())
        except AttributeError:
            sims = np.asarray(sims)

        for i in range(batch_end - batch_start):
            gi = batch_start + i
            for j in card_face_map[face_card_ids[gi]]:
                sims[i, j] = 0.0
            row = sims[i]
            above = row[row > UNIQUENESS_THRESHOLD]
            face_redundancy[gi] = float(np.power(above, UNIQUENESS_POWER).sum())

    # Aggregate face -> card (max redundancy across faces)
    card_redundancy: Dict[str, float] = {}
    for i, cid in enumerate(face_card_ids):
        val = float(face_redundancy[i])
        if cid not in card_redundancy or val > card_redundancy[cid]:
            card_redundancy[cid] = val

    # Log-scaled normalization -> uniqueness 0-100
    raw_vals = np.array(list(card_redundancy.values()))
    max_raw = float(raw_vals.max())
    if max_raw <= 0:
        card_uniqueness = {cid: 100.0 for cid in card_redundancy}
    else:
        log_max = float(np.log1p(max_raw))
        card_uniqueness = {
            cid: round(100.0 * (1.0 - float(np.log1p(raw)) / log_max), 2)
            for cid, raw in card_redundancy.items()
        }

    from ..core.models import Card as CardTable
    cards_table: Table = CardTable.__table__  # type: ignore[assignment]
    stmt = (
        update(cards_table)
        .where(cards_table.c.id == bindparam("_id"))
        .values(uniqueness=bindparam("_score"))
    )
    conn = session.connection()
    mappings = [{"_id": cid, "_score": score} for cid, score in card_uniqueness.items()]
    chunk_size = 1000
    for i in range(0, len(mappings), chunk_size):
        conn.execute(stmt, mappings[i : i + chunk_size])
    session.commit()

    elapsed = time.perf_counter() - t0
    logger.info(
        "Uniqueness scores computed and stored in %.1fs. cards=%d, max_redundancy=%.2f",
        elapsed, len(card_uniqueness), max_raw,
    )


def update_scryfall_data(
    *,
    force: bool = False,
    refresh_tags: bool = False,
    trigger_type: str | None = None,
    strict: bool = False,
) -> bool:
    """
    Download Scryfall oracle bulk file if needed and ingest into DB using diff-ingest.

    Returns True if ingestion ran, False if already up-to-date or download failed.
    """
    setup_loggers()
    ensure_data_dir()
    init_db(mode=INIT_MODE_WORKER)

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

        # Compute uniqueness scores now that all cards are in the DB.
        try:
            with SessionLocal() as uniqueness_session:
                compute_and_store_uniqueness_scores(uniqueness_session)
        except Exception as e:
            logger.error("Uniqueness score computation failed (non-fatal): %s", e, exc_info=True)

        try:
            with SessionLocal() as tags_session:
                run_fetch_tags(tags_session, refresh_tags=refresh_tags)
        except Exception as e:
            logger.error("Tag ingestion failed (non-fatal): %s", e, exc_info=True)

        logger.info("Ingestion succeeded; requesting API TF-IDF rebuild (best-effort).")
        trigger_tfidf_rebuild_best_effort(async_call=True)
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
