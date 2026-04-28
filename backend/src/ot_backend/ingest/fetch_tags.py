from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from typing import TypedDict, cast

import requests
from sqlalchemy import Row, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..core.models import Card, CardRaw, CardRelationship, CardTagging, Tag, TagAncestorMap

logger = logging.getLogger("ot_backend.ingest")

# ---------------------------------------------------------------------------
# Constants / GraphQL
# ---------------------------------------------------------------------------


TAGGER_BASE_URL = "https://tagger.scryfall.com"
TAGGER_GRAPHQL_URL = f"{TAGGER_BASE_URL}/graphql"
SESSION_RESET_BACKOFF_SECONDS = 5.0
REQUEST_TIMEOUT_SECONDS = 10
MAX_SESSION_RESETS: int = 5
ORACLE_FOREIGN_KEY = "oracleId"
TAG_FETCH_BATCH_SIZE = 500
TAG_FETCH_COMMIT_INTERVAL = 25
TAG_FETCH_CONCURRENCY = max(1, int(os.getenv("TAG_FETCH_CONCURRENCY", "4")))
# Per-worker sleep held inside the semaphore slot. Tagger has no public rate
# limit documentation (it's an undocumented internal endpoint of
# tagger.scryfall.com). Scryfall's *main* API is documented at ~10 req/s max
# (https://scryfall.com/docs/api). The defaults below target roughly the same
# aggregate ceiling (4 workers × 0.4 s ≈ 10 req/s) on the assumption Tagger
# shares it — tune down via env if you see repeated 429s.
TAG_FETCH_RATE_LIMIT_SLEEP = float(os.getenv("TAG_FETCH_RATE_LIMIT_SLEEP", "0.4"))

FETCH_CARD_QUERY = """
query FetchCard(
  $set: String!
  $number: String!
  $back: Boolean = false
  $moderatorView: Boolean = false
) {
  card: cardBySet(set: $set, number: $number, back: $back) {
    id
    name
    set
    collectorNumber
    oracleId
    printingId
    illustrationId
    taggings(moderatorView: $moderatorView) {
      id
      annotation
      status
      type
      weight
      relatedId
      foreignKey
      tag {
        id
        name
        description
        type
        namespace
        slug
        ancestorTags {
          id
          name
          description
          type
          namespace
          slug
        }
      }
    }
    relationships(moderatorView: $moderatorView) {
      id
      annotation
      classifier
      classifierInverse
      foreignKey
      relatedId
      relatedName
      subjectId
      subjectName
      status
      type
      weight
    }
  }
}
""".strip()


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class FetchOutcome(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    RESET_SESSION = "reset_session"


@dataclass(frozen=True)
class FetchResult:
    outcome: FetchOutcome
    oracle_tag_count: int = 0
    relationship_count: int = 0


@dataclass(frozen=True)
class TagFetchStats:
    processed_count: int
    success_count: int
    failed_count: int
    reset_session_count: int
    inserted_oracle_taggings: int
    inserted_relationships: int


class TagRecord(TypedDict):
    id: str
    tag_name: str
    tag_description: str | None
    tag_type: str | None
    tag_namespace: str | None
    tag_slug: str | None


class TaggingRecord(TypedDict):
    id: str
    tag_id: str
    foreign_key: str | None
    status: str | None
    tagging_type: str | None
    weight: str | None
    annotation: str | None
    related_id: str | None


class AncestorEdgeRecord(TypedDict):
    tag_id: str
    ancestor_tag_id: str


class RelationshipRecord(TypedDict):
    id: str
    foreign_key: str | None
    classifier: str | None
    classifier_inverse: str | None
    status: str | None
    relationship_type: str | None
    weight: str | None
    annotation: str | None
    subject_remote_id: str | None
    subject_name: str | None
    related_remote_id: str | None
    related_name: str | None


class ExtractedCardEntities(TypedDict):
    tags: list[TagRecord]
    taggings: list[TaggingRecord]
    ancestor_edges: list[AncestorEdgeRecord]
    relationships: list[RelationshipRecord]


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def _normalize_tag_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    tag = value.strip()
    return tag or None


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _format_progress_line(
    *,
    current: int,
    total: int,
    name: str,
    oracle_id: str,
    oracle_tag_count: int,
    relationship_count: int,
) -> str:
    counter_width = len(str(total))
    progress = f"{current:>{counter_width}}/{total}"
    percentage = (current / total) * 100 if total else 0.0
    card_name = name[:20].ljust(20)
    return (
        f"{progress} [{percentage:5.1f}%] : "
        f"{card_name} - {oracle_id} - "
        f"ot:{oracle_tag_count:03d}, rel:{relationship_count:03d}"
    )


def _extract_card_entities(payload: object) -> ExtractedCardEntities:
    if not isinstance(payload, dict):
        return {
            "tags": [],
            "taggings": [],
            "ancestor_edges": [],
            "relationships": [],
        }

    card = payload.get("data", {}).get("card") or {}
    taggings = card.get("taggings") or []
    relationships = card.get("relationships") or []

    tags_by_id: dict[str, TagRecord] = {}
    direct_taggings: list[TaggingRecord] = []
    ancestor_edges: set[tuple[str, str]] = set()
    extracted_relationships: list[RelationshipRecord] = []

    def upsert_tag(raw_tag: object) -> str | None:
        if not isinstance(raw_tag, dict):
            return None
        tag_id = _normalize_tag_value(raw_tag.get("id"))
        tag_name = _normalize_tag_value(raw_tag.get("name"))
        if not tag_id or not tag_name:
            return None
        existing = tags_by_id.get(tag_id)
        tags_by_id[tag_id] = {
            "id": tag_id,
            "tag_name": tag_name,
            "tag_description": _normalize_optional_text(raw_tag.get("description"))
            or (existing["tag_description"] if existing else None),
            "tag_type": _normalize_optional_text(raw_tag.get("type")) or (existing["tag_type"] if existing else None),
            "tag_namespace": _normalize_optional_text(raw_tag.get("namespace"))
            or (existing["tag_namespace"] if existing else None),
            "tag_slug": _normalize_optional_text(raw_tag.get("slug")) or (existing["tag_slug"] if existing else None),
        }
        return tag_id

    for tagging in taggings:
        if not isinstance(tagging, dict):
            continue
        foreign_key = _normalize_optional_text(tagging.get("foreignKey"))
        if foreign_key != ORACLE_FOREIGN_KEY:
            continue
        raw_tag = tagging.get("tag")
        if not isinstance(raw_tag, dict):
            continue
        tag = cast(dict[str, object], raw_tag)
        tag_id = upsert_tag(tag)
        tagging_id = _normalize_tag_value(tagging.get("id"))
        if not tagging_id or not tag_id:
            continue
        direct_taggings.append(
            {
                "id": tagging_id,
                "tag_id": tag_id,
                "foreign_key": foreign_key,
                "status": _normalize_optional_text(tagging.get("status")),
                "tagging_type": _normalize_optional_text(tagging.get("type")),
                "weight": _normalize_optional_text(tagging.get("weight")),
                "annotation": _normalize_optional_text(tagging.get("annotation")),
                "related_id": _normalize_optional_text(tagging.get("relatedId")),
            }
        )
        ancestor_tags = tag.get("ancestorTags")
        if isinstance(ancestor_tags, list):
            for ancestor_tag in ancestor_tags:
                ancestor_id = upsert_tag(ancestor_tag)
                if ancestor_id and ancestor_id != tag_id:
                    ancestor_edges.add((tag_id, ancestor_id))

    for relationship in relationships:
        if not isinstance(relationship, dict):
            continue
        foreign_key = _normalize_optional_text(relationship.get("foreignKey"))
        if foreign_key != ORACLE_FOREIGN_KEY:
            continue
        relationship_id = _normalize_tag_value(relationship.get("id"))
        if not relationship_id:
            continue
        extracted_relationships.append(
            {
                "id": relationship_id,
                "foreign_key": foreign_key,
                "classifier": _normalize_optional_text(relationship.get("classifier")),
                "classifier_inverse": _normalize_optional_text(relationship.get("classifierInverse")),
                "status": _normalize_optional_text(relationship.get("status")),
                "relationship_type": _normalize_optional_text(relationship.get("type")),
                "weight": _normalize_optional_text(relationship.get("weight")),
                "annotation": _normalize_optional_text(relationship.get("annotation")),
                "subject_remote_id": _normalize_optional_text(relationship.get("subjectId")),
                "subject_name": _normalize_optional_text(relationship.get("subjectName")),
                "related_remote_id": _normalize_optional_text(relationship.get("relatedId")),
                "related_name": _normalize_optional_text(relationship.get("relatedName")),
            }
        )

    return {
        "tags": list(tags_by_id.values()),
        "taggings": direct_taggings,
        "ancestor_edges": [{"tag_id": tag_id, "ancestor_tag_id": ancestor_id} for tag_id, ancestor_id in sorted(ancestor_edges)],
        "relationships": extracted_relationships,
    }


# ---------------------------------------------------------------------------
# HTTP / session
# ---------------------------------------------------------------------------


def _create_tagger_session() -> tuple[requests.Session, str]:
    session = requests.Session()
    try:
        response = session.get(TAGGER_BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception as e:
        logger.warning("Tagger homepage GET failed during session bootstrap: %s", e)
        raise
    if response.status_code != 200:
        logger.warning(
            "Tagger homepage returned HTTP %s during session bootstrap; body=%r",
            response.status_code,
            response.text[:200],
        )
        response.raise_for_status()

    csrf_token: str | None = None
    marker = 'name="csrf-token" content="'
    for line in response.text.splitlines():
        if marker not in line:
            continue
        csrf_token = line.split(marker, 1)[1].split('"', 1)[0].strip()
        break

    if not csrf_token:
        logger.warning("Tagger homepage did not include a csrf-token meta tag.")
        raise RuntimeError("Tagger CSRF token not found in homepage response.")
    return session, csrf_token


# ---------------------------------------------------------------------------
# DB writes
# ---------------------------------------------------------------------------


def _flush_card_batch(db: Session, batch: list[tuple[str, ExtractedCardEntities]]) -> None:
    """Write all extracted entities for `batch` cards in one go.

    Operates entirely through the Core API (no ORM identity map), so memory
    stays flat regardless of how many cards have been ingested. All writes
    are coalesced into one statement per table per batch.
    """
    if not batch:
        return

    card_ids = [card_id for card_id, _ in batch]

    tags_by_id: dict[str, TagRecord] = {}
    ancestor_edges_set: set[tuple[str, str]] = set()
    tagging_rows: list[dict[str, object]] = []
    relationship_rows: list[dict[str, object]] = []
    direct_tag_ids: set[str] = set()

    for card_id, extracted in batch:
        for tag_data in extracted["tags"]:
            # Last writer wins on overlapping tag rows inside the batch — the
            # fields are the same across cards, it's just metadata about the
            # tag itself.
            tags_by_id[tag_data["id"]] = tag_data
        for edge in extracted["ancestor_edges"]:
            ancestor_edges_set.add((edge["tag_id"], edge["ancestor_tag_id"]))
        for tagging in extracted["taggings"]:
            tag_id = tagging.get("tag_id")
            if tag_id:
                direct_tag_ids.add(tag_id)
            tagging_rows.append(
                {
                    "id": tagging["id"],
                    "card_id": card_id,
                    "tag_id": tagging["tag_id"],
                    "foreign_key": tagging.get("foreign_key"),
                    "status": tagging.get("status"),
                    "tagging_type": tagging.get("tagging_type"),
                    "weight": tagging.get("weight"),
                    "annotation": tagging.get("annotation"),
                    "related_id": tagging.get("related_id"),
                }
            )
        for relationship in extracted["relationships"]:
            relationship_rows.append(
                {
                    "id": relationship["id"],
                    "card_id": card_id,
                    "foreign_key": relationship.get("foreign_key"),
                    "classifier": relationship.get("classifier"),
                    "classifier_inverse": relationship.get("classifier_inverse"),
                    "status": relationship.get("status"),
                    "relationship_type": relationship.get("relationship_type"),
                    "weight": relationship.get("weight"),
                    "annotation": relationship.get("annotation"),
                    "subject_remote_id": relationship.get("subject_remote_id"),
                    "subject_name": relationship.get("subject_name"),
                    "related_remote_id": relationship.get("related_remote_id"),
                    "related_name": relationship.get("related_name"),
                }
            )

    # One DELETE per table for the whole batch.
    db.execute(delete(CardRelationship).where(CardRelationship.card_id.in_(card_ids)))
    db.execute(delete(CardTagging).where(CardTagging.card_id.in_(card_ids)))

    # Upsert Tag rows through Core API — bypasses identity map entirely.
    # COALESCE(EXCLUDED.x, tags.x) preserves an existing field when the new
    # payload has NULL for that field (matches the old per-card behavior).
    if tags_by_id:
        tag_rows = [
            {
                "id": t["id"],
                "tag_name": t["tag_name"] or "",
                "tag_description": t.get("tag_description"),
                "tag_type": t.get("tag_type"),
                "tag_namespace": t.get("tag_namespace"),
                "tag_slug": t.get("tag_slug"),
            }
            for t in tags_by_id.values()
        ]
        tag_stmt = pg_insert(Tag).values(tag_rows)
        db.execute(
            tag_stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "tag_name": tag_stmt.excluded.tag_name,
                    "tag_description": func.coalesce(tag_stmt.excluded.tag_description, Tag.__table__.c.tag_description),
                    "tag_type": func.coalesce(tag_stmt.excluded.tag_type, Tag.__table__.c.tag_type),
                    "tag_namespace": func.coalesce(tag_stmt.excluded.tag_namespace, Tag.__table__.c.tag_namespace),
                    "tag_slug": func.coalesce(tag_stmt.excluded.tag_slug, Tag.__table__.c.tag_slug),
                },
            )
        )

    if direct_tag_ids:
        db.execute(delete(TagAncestorMap).where(TagAncestorMap.tag_id.in_(direct_tag_ids)))

    if ancestor_edges_set:
        ancestor_stmt = pg_insert(TagAncestorMap).values(
            [{"tag_id": tag_id, "ancestor_tag_id": ancestor_id} for tag_id, ancestor_id in sorted(ancestor_edges_set)]
        )
        db.execute(ancestor_stmt.on_conflict_do_nothing())

    if tagging_rows:
        tagging_stmt = pg_insert(CardTagging).values(tagging_rows)
        db.execute(tagging_stmt.on_conflict_do_nothing(index_elements=["id"]))

    if relationship_rows:
        # Tagger returns the same relationship id from both linked cards.
        # First writer inside the batch wins the card_id column; subsequent
        # duplicates (same id across cards) are silently skipped.
        rel_stmt = pg_insert(CardRelationship).values(relationship_rows)
        db.execute(rel_stmt.on_conflict_do_nothing(index_elements=["id"]))


@dataclass(frozen=True)
class FetchExtraction:
    """Result of a Tagger HTTP call; the DB write happens on the main thread."""

    outcome: FetchOutcome
    extracted: ExtractedCardEntities | None = None


def _tagger_graphql_once(
    session: requests.Session,
    csrf_token: str,
    scryfall_set: str,
    collector_number: str,
    card_id: str,
) -> FetchExtraction:
    try:
        resp = session.post(
            TAGGER_GRAPHQL_URL,
            headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
            json={
                "query": FETCH_CARD_QUERY,
                "variables": {
                    "set": scryfall_set,
                    "number": collector_number,
                    "back": False,
                    "moderatorView": False,
                },
                "operationName": "FetchCard",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as e:
        logger.warning(
            "Tagger GraphQL request raised (%s) for %s (%s/%s)",
            type(e).__name__,
            card_id,
            scryfall_set,
            collector_number,
        )
        return FetchExtraction(FetchOutcome.FAILED)

    if resp.status_code == 429:
        logger.warning(
            "Tagger rate-limited (HTTP 429) for %s (%s/%s); body=%r",
            card_id,
            scryfall_set,
            collector_number,
            resp.text[:200],
        )
        return FetchExtraction(FetchOutcome.RESET_SESSION)

    if resp.status_code >= 500:
        logger.warning(
            "Tagger server error HTTP %s for %s (%s/%s); body=%r",
            resp.status_code,
            card_id,
            scryfall_set,
            collector_number,
            resp.text[:200],
        )
        return FetchExtraction(FetchOutcome.RESET_SESSION)

    if resp.status_code != 200:
        logger.warning(
            "Tagger returned HTTP %s for %s (%s/%s); body=%r",
            resp.status_code,
            card_id,
            scryfall_set,
            collector_number,
            resp.text[:200],
        )
        return FetchExtraction(FetchOutcome.FAILED)

    try:
        payload = cast(dict[str, object], resp.json())
    except Exception as e:
        logger.info("Tagger JSON parse failed for %s: %s", card_id, e)
        return FetchExtraction(FetchOutcome.FAILED)

    if payload.get("errors"):
        logger.info("Tagger GraphQL errors for %s: %s", card_id, payload["errors"])
        return FetchExtraction(FetchOutcome.FAILED)

    return FetchExtraction(FetchOutcome.SUCCESS, _extract_card_entities(payload))


# Per-thread Tagger session (requests.Session is not thread-safe).
_thread_local = threading.local()


def _worker_session() -> tuple[requests.Session, str]:
    state = getattr(_thread_local, "state", None)
    if state is not None:
        return state
    session, csrf = _create_tagger_session()
    _thread_local.state = (session, csrf)
    return session, csrf


def _reset_worker_session() -> tuple[requests.Session, str]:
    state = getattr(_thread_local, "state", None)
    if state is not None:
        try:
            state[0].close()
        except Exception:
            logger.debug("Failed to close Tagger session cleanly.", exc_info=True)
    _thread_local.state = None
    time.sleep(SESSION_RESET_BACKOFF_SECONDS)
    return _worker_session()


def _close_worker_session() -> None:
    state = getattr(_thread_local, "state", None)
    if state is not None:
        try:
            state[0].close()
        except Exception:
            logger.debug("Failed to close Tagger session cleanly.", exc_info=True)
        _thread_local.state = None


def _fetch_card_extraction(
    card: Row[tuple[str, str, str, str]],
    rate_sem: threading.Semaphore,
) -> FetchExtraction:
    if not card.set_code or not card.collector_number:
        return FetchExtraction(FetchOutcome.FAILED)

    resets = 0
    while True:
        with rate_sem:
            session, csrf_token = _worker_session()
            started = time.monotonic()
            result = _tagger_graphql_once(
                session, csrf_token, card.set_code, card.collector_number, card.oracle_id
            )
            elapsed = time.monotonic() - started
            # Surface any request that takes unusually long — helps spot a slow
            # Tagger endpoint that isn't an outright 4xx/5xx.
            if elapsed > 3.0:
                logger.warning(
                    "Tagger slow response for %s (%s/%s): %.1fs outcome=%s",
                    card.oracle_id,
                    card.set_code,
                    card.collector_number,
                    elapsed,
                    result.outcome.value,
                )
            time.sleep(TAG_FETCH_RATE_LIMIT_SLEEP)
        if result.outcome != FetchOutcome.RESET_SESSION:
            return result
        resets += 1
        logger.warning(
            "Tagger session reset #%d for %s (%s/%s)",
            resets,
            card.oracle_id,
            card.set_code,
            card.collector_number,
        )
        if resets >= MAX_SESSION_RESETS:
            logger.error(
                "Tagger rate limit: exceeded max session resets for card %s/%s, skipping.",
                card.set_code,
                card.collector_number,
            )
            return FetchExtraction(FetchOutcome.FAILED)
        try:
            _reset_worker_session()
        except Exception as e:
            logger.warning("Tagger session re-bootstrap failed after retryable response: %s", e)
            return FetchExtraction(FetchOutcome.FAILED)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _cards_needing_tag_fetch_query(refresh_tags: bool):
    query = (
        select(Card.oracle_id, Card.name, CardRaw.set_code, CardRaw.collector_number)
        .join(CardRaw, CardRaw.id == Card.scryfall_id)
        .order_by(Card.oracle_id.asc())
    )
    if not refresh_tags:
        query = (
            query.outerjoin(CardTagging, CardTagging.card_id == Card.oracle_id)
            .where(CardTagging.id.is_(None))
        )
    return query


def cards_needing_tag_fetch(db: Session, refresh_tags: bool) -> Sequence[Row[tuple[str, str, str, str]]]:
    return db.execute(_cards_needing_tag_fetch_query(refresh_tags)).all()


def _itercards_needing_tag_fetch(
    db: Session,
    refresh_tags: bool,
    *,
    batch_size: int = TAG_FETCH_BATCH_SIZE,
) -> Iterator[Row[tuple[str, str, str, str]]]:
    last_oracle_id: str | None = None
    while True:
        query = _cards_needing_tag_fetch_query(refresh_tags).limit(batch_size)
        if last_oracle_id is not None:
            query = query.where(Card.oracle_id > last_oracle_id)
        rows = db.execute(query).all()
        if not rows:
            return
        for row in rows:
            yield row
        last_oracle_id = rows[-1].oracle_id


def run_fetch_tags(db: Session, *, refresh_tags: bool = False) -> TagFetchStats:
    total = db.scalar(select(func.count()).select_from(_cards_needing_tag_fetch_query(refresh_tags).subquery())) or 0
    if total == 0:
        logger.info("No cards require Tagger refresh. refresh_tags=%s", refresh_tags)
        return TagFetchStats(
            processed_count=0,
            success_count=0,
            failed_count=0,
            reset_session_count=0,
            inserted_oracle_taggings=0,
            inserted_relationships=0,
        )

    # Eager bootstrap: if the Tagger front door is unreachable we want to bail
    # before spinning up worker threads.
    try:
        _create_tagger_session()
    except Exception as e:
        logger.warning("Tagger session bootstrap failed; skipping community tag ingestion: %s", e)
        return TagFetchStats(
            processed_count=0,
            success_count=0,
            failed_count=0,
            reset_session_count=0,
            inserted_oracle_taggings=0,
            inserted_relationships=0,
        )

    logger.info(
        "Starting tag ingestion. mode=tagger_graphql cards=%d refresh_tags=%s concurrency=%d",
        total,
        refresh_tags,
        TAG_FETCH_CONCURRENCY,
    )

    counts = {FetchOutcome.SUCCESS: 0, FetchOutcome.FAILED: 0, FetchOutcome.RESET_SESSION: 0}
    inserted_oracle_taggings = 0
    inserted_relationships = 0
    processed = 0

    cards = list(_itercards_needing_tag_fetch(db, refresh_tags))
    rate_sem = threading.Semaphore(TAG_FETCH_CONCURRENCY)

    # Stall watchdog: if no card completes for 60 s, log a warning so the
    # operator knows the ingest is stuck rather than quietly chugging.
    stall_stop = threading.Event()
    last_progress_ts = [time.monotonic()]

    def _stall_watch() -> None:
        while not stall_stop.wait(30.0):
            idle = time.monotonic() - last_progress_ts[0]
            if idle > 60.0:
                logger.warning(
                    "Tag ingestion appears stalled: no card completed for %.0fs (processed %d/%d).",
                    idle,
                    processed,
                    total,
                )

    watchdog = threading.Thread(target=_stall_watch, name="tagger-watchdog", daemon=True)
    watchdog.start()

    executor = ThreadPoolExecutor(max_workers=TAG_FETCH_CONCURRENCY, thread_name_prefix="tagger")
    pending_batch: list[tuple[str, ExtractedCardEntities]] = []
    try:
        # Use as_completed so progress streams in completion order. With map()
        # a single slow card blocks visibility of every later card that has
        # already finished — looks like the whole ingest froze.
        future_to_card = {
            executor.submit(_fetch_card_extraction, card, rate_sem): card for card in cards
        }

        for future in as_completed(future_to_card):
            card = future_to_card[future]
            result = future.result()
            last_progress_ts[0] = time.monotonic()
            processed += 1
            counts[result.outcome] += 1
            oracle_tag_count = 0
            relationship_count = 0

            if result.outcome == FetchOutcome.SUCCESS and result.extracted is not None:
                oracle_tag_count = len(result.extracted["taggings"])
                relationship_count = len(result.extracted["relationships"])
                inserted_oracle_taggings += oracle_tag_count
                inserted_relationships += relationship_count
                pending_batch.append((card.oracle_id, result.extracted))
                if len(pending_batch) >= TAG_FETCH_COMMIT_INTERVAL:
                    _flush_card_batch(db, pending_batch)
                    db.commit()
                    pending_batch.clear()

            logger.info(
                _format_progress_line(
                    current=processed,
                    total=total,
                    name=card.name,
                    oracle_id=card.oracle_id,
                    oracle_tag_count=oracle_tag_count,
                    relationship_count=relationship_count,
                )
            )

        # Worker threads own per-thread Tagger sessions; close them before the
        # pool shuts down.
        for _ in range(TAG_FETCH_CONCURRENCY):
            executor.submit(_close_worker_session)
        executor.shutdown(wait=True)
    except BaseException:
        # Cancel any still-pending futures so the default wait-for-all
        # shutdown doesn't stall the process for the thousands of queued
        # cards that haven't started yet.
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    finally:
        stall_stop.set()
        watchdog.join(timeout=1.0)

    if pending_batch:
        _flush_card_batch(db, pending_batch)
        db.commit()
        pending_batch.clear()

    logger.info(
        "Tag ingestion complete. success=%d failed=%d inserted: ot=%d rel=%d",
        counts[FetchOutcome.SUCCESS],
        counts[FetchOutcome.FAILED],
        inserted_oracle_taggings,
        inserted_relationships,
    )
    return TagFetchStats(
        processed_count=processed,
        success_count=counts[FetchOutcome.SUCCESS],
        failed_count=counts[FetchOutcome.FAILED],
        reset_session_count=counts[FetchOutcome.RESET_SESSION],
        inserted_oracle_taggings=inserted_oracle_taggings,
        inserted_relationships=inserted_relationships,
    )
