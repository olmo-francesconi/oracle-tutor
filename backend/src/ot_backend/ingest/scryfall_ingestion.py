from __future__ import annotations

import gzip
import json
import logging
import shutil
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import IO, Any
from urllib.parse import urlparse

import requests
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..core.config import (
    CARDS_BULK_FILE,
    DATA_DIR,
    DB_SCHEMA_VERSION,
    SCRYFALL_DATA_KEY,
    ensure_data_dir,
)
from ..core.database import SessionLocal
from ..core.db_init import MIGRATION_STATE_READY, get_migration_state, parse_version
from ..core.logging_config import setup_loggers
from ..core.models import (
    Card,
    CardFace,
    CardFaceAbility,
    CardRaw,
    CardRelationship,
    CardTagging,
    IngestionLog,
    SystemMetadata,
)
from ..semantic.ability_split import build_face_abilities
from ..semantic.semantic_state import bump_semantic_data_version
from .fetch_tags import run_fetch_tags

logger = logging.getLogger("ot_backend.ingest")

BULK_DATA_URL = "https://api.scryfall.com/bulk-data/default-cards"
# Scryfall rejects requests without an explicit User-Agent and Accept header (HTTP 400/403).
SCRYFALL_HEADERS = {
    "User-Agent": "OracleTutor/1.0 (+https://oracletutor.org)",
    "Accept": "application/json",
}
BATCH_SIZE = 500
CHUNK_SIZE = 1_000
REDUCTION_LOG_INTERVAL = 10_000
SKIPPED_LAYOUTS = (
    "token",
    "double_faced_token",
    "art_series",
    "emblem",
    "planar",
    "scheme",
    "vanguard",
)

META_JSON = DATA_DIR / "scryfall_meta.json"
TEMP_CARDS_FILE = DATA_DIR / "scryfall-cards-temp.jsonl.gz"
GZIP_MAGIC = b"\x1f\x8b"


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _parse_released_at(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _format_stage_progress(*, current: int, total: int) -> str:
    width = len(str(total)) if total > 0 else 1
    percent = (current / total) * 100 if total else 0.0
    return f"{current:>{width}}/{total} [{percent:5.1f}%]"


def _log_batch_progress(*, stage: str, current: int, total: int, items_in_batch: int) -> None:
    logger.info("%s %s batch_items=%d", stage, _format_stage_progress(current=current, total=total), items_in_batch)


def _delete_card_related_rows(session: Session, oracle_ids: list[str]) -> None:
    if not oracle_ids:
        return

    for i in range(0, len(oracle_ids), CHUNK_SIZE):
        chunk = oracle_ids[i : i + CHUNK_SIZE]
        session.execute(delete(CardRelationship).where(CardRelationship.card_id.in_(chunk)))
        session.execute(delete(CardTagging).where(CardTagging.card_id.in_(chunk)))
        session.execute(delete(CardFace).where(CardFace.oracle_id.in_(chunk)))


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


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


def fetch_bulk_metadata(url: str = BULK_DATA_URL) -> dict[str, Any]:
    resp = requests.get(url, timeout=30, headers=SCRYFALL_HEADERS)
    resp.raise_for_status()
    return resp.json()


def save_local_metadata(metadata: dict[str, Any]) -> None:
    with META_JSON.open("w") as f:
        json.dump(metadata, f, indent=2)


def load_local_metadata() -> dict[str, Any] | None:
    if not META_JSON.exists():
        return None
    try:
        with META_JSON.open("r") as f:
            return json.load(f)
    except Exception:
        return None


def resolve_bulk_download_url(metadata: dict[str, Any]) -> str:
    """Extract the bulk-file URL from a Scryfall `bulk_data` object.

    Scryfall replaced the single-JSON-array `download_uri` with a gzipped
    JSON Lines `jsonl_download_uri`. Only the new key exists now; fail loudly
    rather than silently downloading nothing if that ever changes again.
    """
    download_url = metadata.get("jsonl_download_uri")
    if not isinstance(download_url, str) or not download_url:
        raise RuntimeError(
            "Scryfall bulk metadata has no 'jsonl_download_uri'; "
            f"available keys: {sorted(metadata)}"
        )
    return download_url


def download_bulk_file(download_url: str, destination: Path = CARDS_BULK_FILE) -> None:
    logger.info("Downloading bulk data...")
    _validate_scryfall_download_url(download_url)
    with requests.get(
        download_url, stream=True, timeout=60, allow_redirects=True, headers=SCRYFALL_HEADERS
    ) as resp:
        resp.raise_for_status()
        # If we were redirected, ensure the final host is still allowed.
        _validate_scryfall_download_url(resp.url)
        with destination.open("wb") as out:
            for chunk in resp.iter_content(chunk_size=1_048_576):
                if chunk:
                    out.write(chunk)
    logger.info("Download complete.")


def _open_bulk_stream(path: Path) -> gzip.GzipFile | IO[bytes]:
    """Open a bulk file, transparently gunzipping it.

    Scryfall serves `.jsonl.gz` with `Content-Type: application/gzip` and no
    `Content-Encoding`, so the bytes we wrote are still compressed. Sniff the
    magic anyway: if a proxy ever decompresses in transit we'd have plain
    JSONL under a `.gz` name.
    """
    with path.open("rb") as probe:
        is_gzip = probe.read(2) == GZIP_MAGIC
    return gzip.open(path, "rb") if is_gzip else path.open("rb")


def iter_bulk_cards(path: Path) -> Iterator[dict[str, Any]]:
    """Stream card objects out of a Scryfall JSON Lines bulk file."""
    with _open_bulk_stream(path) as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if not line:
                continue
            yield json.loads(line)


def should_skip_card(card: dict[str, Any]) -> bool:
    """
    Return True for Scryfall records we don't want in the playable search corpus.

    Notes:
    - We intentionally ingest from Scryfall's `default-cards` bulk file (every printing,
      so `cards_raw` is complete and `select_best_printing` can pick a representative).
      It includes several non-game-piece records.
    - A common culprit is "Theme Cards" used in Jumpstart-style products. These have
      `type_line == "Card"` and oracle text like "(Theme color: {R})".
    """

    if card.get("layout") in SKIPPED_LAYOUTS:
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


def cleanup_unplayable_cards(session: Session) -> dict[str, int]:
    """
    Best-effort cleanup for unplayable records that may have been ingested previously.

    We remove:
    - Cards with layouts we always skip.
    - Cards that have at least one face with `type_line == "Card"` (Theme Cards).

    Returns lightweight stats for logging.
    """

    stats = {"deleted_cards_by_layout": 0, "deleted_cards_by_type_line_card": 0}

    # Delete dependent rows explicitly before the parent delete.
    ids_by_layout = list(session.scalars(select(Card.oracle_id).where(Card.layout.in_(SKIPPED_LAYOUTS))).all())
    _delete_card_related_rows(session, ids_by_layout)
    res = session.execute(delete(Card).where(Card.oracle_id.in_(ids_by_layout)))
    stats["deleted_cards_by_layout"] = int(getattr(res, "rowcount", 0) or len(ids_by_layout))

    # Delete Theme Cards (type_line == "Card") (again: delete faces first for safety).
    ids_by_face_card = list(
        session.scalars(select(CardFace.oracle_id).where(CardFace.type_line == "Card").distinct()).all()
    )
    _delete_card_related_rows(session, ids_by_face_card)
    res = session.execute(delete(Card).where(Card.oracle_id.in_(ids_by_face_card)))
    stats["deleted_cards_by_type_line_card"] = int(getattr(res, "rowcount", 0) or len(ids_by_face_card))

    return stats


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def prepare_raw_card(card_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": card_data.get("id"),
        "oracle_id": card_data.get("oracle_id"),
        "name": card_data.get("name"),
        "lang": card_data.get("lang"),
        "layout": card_data.get("layout"),
        "cmc": card_data.get("cmc"),
        "mana_cost": card_data.get("mana_cost"),
        "type_line": card_data.get("type_line"),
        "oracle_text": card_data.get("oracle_text"),
        "colors": card_data.get("colors"),
        "color_identity": card_data.get("color_identity"),
        "color_indicator": card_data.get("color_indicator"),
        "keywords": card_data.get("keywords"),
        "legalities": card_data.get("legalities"),
        "power": card_data.get("power"),
        "toughness": card_data.get("toughness"),
        "loyalty": card_data.get("loyalty"),
        "defense": card_data.get("defense"),
        "rarity": card_data.get("rarity"),
        "set_code": card_data.get("set"),
        "set_id": card_data.get("set_id"),
        "set_name": card_data.get("set_name"),
        "set_type": card_data.get("set_type"),
        "collector_number": card_data.get("collector_number"),
        "released_at": _parse_released_at(card_data.get("released_at")),
        "artist": card_data.get("artist"),
        "illustration_id": card_data.get("illustration_id"),
        "image_status": card_data.get("image_status"),
        "image_uris": card_data.get("image_uris"),
        "card_faces_json": card_data.get("card_faces"),
        "all_parts": card_data.get("all_parts"),
        "games": card_data.get("games"),
        "finishes": card_data.get("finishes"),
        "digital": card_data.get("digital"),
        "booster": card_data.get("booster"),
        "promo": card_data.get("promo"),
        "promo_types": card_data.get("promo_types"),
        "reprint": card_data.get("reprint"),
        "variation": card_data.get("variation"),
        "variation_of": card_data.get("variation_of"),
        "full_art": card_data.get("full_art"),
        "textless": card_data.get("textless"),
        "story_spotlight": card_data.get("story_spotlight"),
        "border_color": card_data.get("border_color"),
        "frame": card_data.get("frame"),
        "frame_effects": card_data.get("frame_effects"),
        "watermark": card_data.get("watermark"),
        "edhrec_rank": card_data.get("edhrec_rank"),
        "prices": card_data.get("prices"),
        "arena_id": card_data.get("arena_id"),
        "mtgo_id": card_data.get("mtgo_id"),
        "tcgplayer_id": card_data.get("tcgplayer_id"),
        "cardmarket_id": card_data.get("cardmarket_id"),
        "multiverse_ids": card_data.get("multiverse_ids"),
        "flavor_text": card_data.get("flavor_text"),
        "flavor_name": card_data.get("flavor_name"),
        "content_warning": card_data.get("content_warning"),
        "ingested_at": _utcnow_naive(),
    }


def prepare_parent_card(card_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "oracle_id": card_data.get("oracle_id"),
        "scryfall_id": card_data.get("id"),
        "name": card_data.get("name"),
        "layout": card_data.get("layout"),
        "cmc": card_data.get("cmc"),
        "edhrec_rank": card_data.get("edhrec_rank"),
        "rarity": card_data.get("rarity"),
        "legalities": card_data.get("legalities"),
        "color_identity": card_data.get("color_identity"),
    }


KNOWN_CARD_TYPE_CATEGORIES: frozenset[str] = frozenset(
    {"creature", "instant", "sorcery", "enchantment", "artifact", "planeswalker", "land"}
)


def _extract_type_categories(type_line: str | None) -> list[str]:
    """Return the normalized primary card types from a Scryfall type_line.

    Type lines look like "Legendary Creature — Human Soldier"; primary types
    always sit on the LHS of the em dash. Anything not in the whitelist is
    dropped (supertypes like "Legendary", unusual subtypes, etc.).
    """
    if not type_line:
        return []
    lhs = type_line.split("—", 1)[0]
    tokens = {word.lower() for word in lhs.split() if word}
    return sorted(token for token in tokens if token in KNOWN_CARD_TYPE_CATEGORIES)


def prepare_card_face(oracle_id: str, face_ix: int, face_data: dict[str, Any]) -> dict[str, Any]:
    type_line = face_data.get("type_line")
    return {
        "oracle_id": oracle_id,
        "face_ix": face_ix,
        "scryfall_face_oracle_id": face_data.get("oracle_id"),
        "name": face_data.get("name"),
        "mana_cost": face_data.get("mana_cost"),
        "type_line": type_line,
        "type_categories": _extract_type_categories(type_line),
        "oracle_text": face_data.get("oracle_text"),
        "power": face_data.get("power"),
        "toughness": face_data.get("toughness"),
        "loyalty": face_data.get("loyalty"),
        "defense": face_data.get("defense"),
        "colors": face_data.get("colors"),
        "color_indicator": face_data.get("color_indicator"),
        "image_uris": face_data.get("image_uris"),
        "artist": face_data.get("artist"),
        "flavor_text": face_data.get("flavor_text"),
        "cmc": face_data.get("cmc"),
    }


def prepare_face_abilities(oracle_id: str, face_ix: int, face_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Segment a face's oracle text into the rows backing `card_face_abilities`."""
    abilities = build_face_abilities(
        oracle_text=face_data.get("oracle_text"),
        card_name=face_data.get("name") or "",
        type_line=face_data.get("type_line") or "",
    )
    return [
        {
            "oracle_id": oracle_id,
            "face_ix": face_ix,
            "ability_ix": ability.ability_ix,
            "text": ability.text,
            "normalized_text": ability.normalized_text,
            "text_hash": ability.text_hash,
            "is_keyword": ability.is_keyword,
        }
        for ability in abilities
    ]


def ingest_batch(session: Session, batch_cards: list[dict[str, Any]]) -> None:
    if not batch_cards:
        return

    raw_cards: list[dict[str, Any]] = []
    parents: list[dict[str, Any]] = []
    faces_to_insert: list[dict[str, Any]] = []
    abilities_to_insert: list[dict[str, Any]] = []
    face_oracle_ids: set[str] = set()

    for card in batch_cards:
        card_id = card.get("id")
        if not isinstance(card_id, str) or not card_id:
            continue
        raw_cards.append(prepare_raw_card(card))
        oracle_id = card.get("oracle_id")
        if not isinstance(oracle_id, str) or not oracle_id:
            continue
        parents.append(prepare_parent_card(card))
        face_oracle_ids.add(oracle_id)
        faces = card.get("card_faces") or [card]
        for face_ix, face in enumerate(faces):
            faces_to_insert.append(prepare_card_face(oracle_id, face_ix, face))
            abilities_to_insert.extend(prepare_face_abilities(oracle_id, face_ix, face))

    raw_stmt = insert(CardRaw).values(raw_cards)
    raw_stmt = raw_stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            column.name: getattr(raw_stmt.excluded, column.name)
            for column in CardRaw.__table__.columns
            if column.name != "id"
        },
    )
    session.execute(raw_stmt)

    if parents:
        parent_stmt = insert(Card).values(parents)
        parent_stmt = parent_stmt.on_conflict_do_update(
            index_elements=["oracle_id"],
            set_={
                "scryfall_id": parent_stmt.excluded.scryfall_id,
                "name": parent_stmt.excluded.name,
                "layout": parent_stmt.excluded.layout,
                "cmc": parent_stmt.excluded.cmc,
                "edhrec_rank": parent_stmt.excluded.edhrec_rank,
                "rarity": parent_stmt.excluded.rarity,
                "legalities": parent_stmt.excluded.legalities,
                "color_identity": parent_stmt.excluded.color_identity,
            },
        )
        session.execute(parent_stmt)

    parent_oracle_ids = list(face_oracle_ids)
    _delete_card_related_rows(session, parent_oracle_ids)

    if faces_to_insert:
        session.execute(insert(CardFace).values(faces_to_insert))
    # Must follow the face insert: card_face_abilities FKs (oracle_id, face_ix).
    # The delete above removed the previous generation via ON DELETE CASCADE.
    if abilities_to_insert:
        session.execute(insert(CardFaceAbility).values(abilities_to_insert))


def select_best_printing(current: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
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


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def ingest_data_diff(
    new_path: Path,
    scryfall_metadata: dict[str, Any],
    *,
    trigger_type: str = "scheduled",
) -> None:
    logger.info("Stage: start database ingestion")
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

        logger.info("Stage: read and reduce bulk data")
        best_printings: dict[str, dict[str, Any]] = {}
        seen_scryfall_ids: set[str] = set()
        stats = {"seen": 0, "kept": 0, "skipped": 0}

        for card in iter_bulk_cards(new_path):
            stats["seen"] += 1
            if stats["seen"] % REDUCTION_LOG_INTERVAL == 0:
                logger.info(
                    "Reduce progress seen=%d kept=%d skipped=%d",
                    stats["seen"],
                    len(best_printings),
                    stats["skipped"],
                )
            scryfall_id = card.get("id")
            if isinstance(scryfall_id, str) and scryfall_id:
                seen_scryfall_ids.add(scryfall_id)
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

        existing_oracle_ids = set(session.scalars(select(Card.oracle_id)).all())
        logger.info("Found %d existing cards in DB.", len(existing_oracle_ids))

        ingest_stats = {"added": 0, "modified": 0, "deleted": 0, "unchanged": 0}
        batch: list[dict[str, Any]] = []
        total_kept = len(best_printings)
        total_upsert_batches = max((total_kept + BATCH_SIZE - 1) // BATCH_SIZE, 1) if total_kept else 0
        processed_cards = 0
        completed_upsert_batches = 0

        if total_kept:
            logger.info(
                "Stage: upsert cards total_cards=%d batches=%d batch_size=%d",
                total_kept,
                total_upsert_batches,
                BATCH_SIZE,
            )

        for card in best_printings.values():
            oracle_id = card.get("oracle_id")
            if not isinstance(oracle_id, str) or not oracle_id:
                continue
            if oracle_id in existing_oracle_ids:
                existing_oracle_ids.remove(oracle_id)
                ingest_stats["unchanged"] += 1
            else:
                ingest_stats["added"] += 1

            batch.append(card)
            if len(batch) >= BATCH_SIZE:
                batch_size = len(batch)
                ingest_batch(session, batch)
                session.commit()
                processed_cards += batch_size
                completed_upsert_batches += 1
                _log_batch_progress(
                    stage="Upsert progress",
                    current=completed_upsert_batches,
                    total=total_upsert_batches,
                    items_in_batch=batch_size,
                )
                batch = []

        if batch:
            batch_size = len(batch)
            ingest_batch(session, batch)
            session.commit()
            processed_cards += batch_size
            completed_upsert_batches += 1
            _log_batch_progress(
                stage="Upsert progress",
                current=completed_upsert_batches,
                total=total_upsert_batches,
                items_in_batch=batch_size,
            )

        if total_kept:
            logger.info("Stage: upsert cards complete processed=%d", processed_cards)

        # Delete phase + sys_meta update run in a single transaction so a
        # crash cannot leave a split state (e.g. obsolete cards removed but
        # their card_raw rows left behind, or sys_meta pointing at a bulk file
        # that wasn't fully reconciled).
        ingest_stats["deleted"] = len(existing_oracle_ids)
        if existing_oracle_ids:
            logger.info("Stage: delete obsolete cards total=%d", len(existing_oracle_ids))
            existing_oracle_ids_list = list(existing_oracle_ids)
            total_delete_batches = (len(existing_oracle_ids_list) + CHUNK_SIZE - 1) // CHUNK_SIZE
            for batch_ix, i in enumerate(range(0, len(existing_oracle_ids_list), CHUNK_SIZE), start=1):
                chunk = existing_oracle_ids_list[i : i + CHUNK_SIZE]
                _delete_card_related_rows(session, chunk)
                session.execute(delete(Card).where(Card.oracle_id.in_(chunk)))
                session.flush()
                _log_batch_progress(
                    stage="Delete cards",
                    current=batch_ix,
                    total=total_delete_batches,
                    items_in_batch=len(chunk),
                )

        obsolete_raw_batch: list[str] = []
        raw_delete_batches = 0
        raw_delete_count = 0
        for raw_id in session.scalars(select(CardRaw.id)):
            if raw_id in seen_scryfall_ids:
                continue
            obsolete_raw_batch.append(raw_id)
            if len(obsolete_raw_batch) < CHUNK_SIZE:
                continue
            raw_delete_batches += 1
            raw_delete_count += len(obsolete_raw_batch)
            session.execute(delete(CardRaw).where(CardRaw.id.in_(obsolete_raw_batch)))
            session.flush()
            obsolete_raw_batch = []
        if obsolete_raw_batch:
            raw_delete_batches += 1
            raw_delete_count += len(obsolete_raw_batch)
            session.execute(delete(CardRaw).where(CardRaw.id.in_(obsolete_raw_batch)))
            session.flush()
        if raw_delete_count:
            logger.info("Stage: delete obsolete raw printings complete total=%d", raw_delete_count)

        sys_meta = SystemMetadata(
            key=SCRYFALL_DATA_KEY,
            updated_at=scryfall_metadata.get("updated_at") or "",
            last_ingestion=_utcnow_naive(),
            version=DB_SCHEMA_VERSION,
        )
        session.merge(sys_meta)

        log_entry = session.get(IngestionLog, log_id)
        if log_entry:
            log_entry.status = "success"
            log_entry.completed_at = _utcnow_naive()
            log_entry.records_processed = ingest_stats["added"] + ingest_stats["unchanged"]
            log_entry.records_skipped = stats["skipped"]
            log_entry.error_message = json.dumps(ingest_stats)

        session.commit()
        logger.info("Stage: database ingestion complete stats=%s", ingest_stats)
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


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def update_scryfall_data(
    *,
    force: bool = False,
    refresh_tags: bool = False,
    skip_tags: bool = False,
    trigger_type: str | None = None,
    strict: bool = False,
) -> bool:
    """
    Download Scryfall oracle bulk file if needed and ingest into DB using diff-ingest.

    Returns True if ingestion ran, False if already up-to-date or download failed.
    """
    setup_loggers()
    ensure_data_dir()

    state = get_migration_state()
    if state != MIGRATION_STATE_READY:
        raise RuntimeError(
            f"DB schema is not ready (state={state!r}). "
            "Ensure the API has run migrations before starting the worker."
        )

    remote_meta: dict[str, Any] | None = None
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
    file_exists = CARDS_BULK_FILE.exists()

    # DB metadata check
    session = SessionLocal()
    db_updated_at: str | None = None
    db_schema_version = "0.0"
    db_is_empty = True
    try:
        db_meta = session.get(SystemMetadata, SCRYFALL_DATA_KEY)
        if db_meta:
            db_updated_at = db_meta.updated_at
            db_schema_version = db_meta.version or "0.0"

        card_count = session.query(func.count(Card.oracle_id)).scalar()
        db_is_empty = (card_count == 0)
    finally:
        session.close()

    logger.info("Status: Remote=%s, Local=%s, DB=%s", remote_updated_at, local_updated_at, db_updated_at)

    effective_trigger = trigger_type or ("force" if force else "scheduled")

    schema_needs_ingest = parse_version(str(db_schema_version)) < parse_version(DB_SCHEMA_VERSION)

    # Stateless optimization:
    # If the DB already reflects the latest remote version, we can skip downloading the JSON
    # even if the container has no persisted /app/data directory.
    semantic_changed = False

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
        if not skip_tags:
            try:
                with SessionLocal() as tags_session:
                    tag_stats = run_fetch_tags(tags_session, refresh_tags=refresh_tags)
                    semantic_changed = tag_stats.success_count > 0
            except Exception as e:
                logger.error("Tag ingestion failed (non-fatal): %s", e, exc_info=True)
        if semantic_changed:
            with SessionLocal() as semantic_session:
                semantic_version = bump_semantic_data_version(semantic_session)
            logger.info("Semantic data version advanced to %d.", semantic_version)
        return False

    # Download decision
    download_needed = False
    if force:
        download_needed = True
    elif not file_exists or not local_updated_at:
        download_needed = True
    elif remote_updated_at and remote_updated_at != local_updated_at:
        download_needed = True

    ingestion_source = CARDS_BULK_FILE
    if download_needed and remote_meta:
        try:
            download_bulk_file(resolve_bulk_download_url(remote_meta), TEMP_CARDS_FILE)
            ingestion_source = TEMP_CARDS_FILE
        except Exception as e:
            logger.error("Download failed: %s", e)
            if strict:
                raise
            return False
    else:
        if not CARDS_BULK_FILE.exists():
            logger.error("No local data found and download skipped.")
            if strict:
                raise RuntimeError("No local cards.json and remote download was unavailable/skipped.")
            return False

    # Ingestion decision
    ingestion_needed = False
    if ingestion_source == TEMP_CARDS_FILE:
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
    else:
        try:
            ingest_data_diff(
                new_path=ingestion_source,
                scryfall_metadata=remote_meta if remote_meta else (local_meta or {}),
                trigger_type=effective_trigger,
            )

            if ingestion_source == TEMP_CARDS_FILE:
                logger.info("Stage: promote downloaded bulk file")
                shutil.move(str(TEMP_CARDS_FILE), str(CARDS_BULK_FILE))
                if remote_meta:
                    save_local_metadata(remote_meta)

            semantic_changed = True

        except Exception as e:
            logger.error("Update process failed: %s", e, exc_info=True)
            if strict:
                raise
            if TEMP_CARDS_FILE.exists():
                try:
                    TEMP_CARDS_FILE.unlink()
                except Exception:
                    logger.warning("Failed to cleanup temp cards file.")
            return False

    if not skip_tags:
        try:
            logger.info("Stage: ingest community tags")
            with SessionLocal() as tags_session:
                tag_stats = run_fetch_tags(tags_session, refresh_tags=refresh_tags)
                semantic_changed = semantic_changed or tag_stats.success_count > 0
        except Exception as e:
            logger.error("Tag ingestion failed (non-fatal): %s", e, exc_info=True)

    if semantic_changed:
        with SessionLocal() as semantic_session:
            semantic_version = bump_semantic_data_version(semantic_session)
        logger.info("Semantic data version advanced to %d.", semantic_version)

    return ingestion_needed
