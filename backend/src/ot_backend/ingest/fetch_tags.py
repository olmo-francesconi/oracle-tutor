from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import TypedDict, cast

import requests
from sqlalchemy import Row, delete, func, select
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
TAG_FETCH_CONCURRENCY = max(1, int(os.getenv("TAG_FETCH_CONCURRENCY", "6")))

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
    response = session.get(TAGGER_BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    csrf_token: str | None = None
    marker = 'name="csrf-token" content="'
    for line in response.text.splitlines():
        if marker not in line:
            continue
        csrf_token = line.split(marker, 1)[1].split('"', 1)[0].strip()
        break

    if not csrf_token:
        raise RuntimeError("Tagger CSRF token not found in homepage response.")
    return session, csrf_token


# ---------------------------------------------------------------------------
# DB writes
# ---------------------------------------------------------------------------


def _replace_card_entities(db: Session, card_id: str, extracted: ExtractedCardEntities) -> None:
    tags = extracted["tags"]
    taggings = extracted["taggings"]
    ancestor_edges = extracted["ancestor_edges"]
    relationships = extracted["relationships"]
    direct_tag_ids = sorted(
        tagging["tag_id"]
        for tagging in taggings
        if isinstance(tagging.get("tag_id"), str) and tagging["tag_id"]
    )

    _ = db.execute(delete(CardRelationship).where(CardRelationship.card_id == card_id))
    _ = db.execute(delete(CardTagging).where(CardTagging.card_id == card_id))

    tag_ids = [tag_data["id"] for tag_data in tags]
    existing_tags = {
        tag.id: tag
        for tag in db.scalars(select(Tag).where(Tag.id.in_(tag_ids))).all()
    } if tag_ids else {}

    for tag_data in tags:
        tag_id = tag_data["id"]
        tag = existing_tags.get(tag_id)
        if tag is None:
            db.add(
                Tag(
                    id=tag_id,
                    tag_name=tag_data["tag_name"] or "",
                    tag_description=tag_data.get("tag_description"),
                    tag_type=tag_data.get("tag_type"),
                    tag_namespace=tag_data.get("tag_namespace"),
                    tag_slug=tag_data.get("tag_slug"),
                )
            )
            continue

        tag.tag_name = tag_data["tag_name"] or tag.tag_name
        if tag_data.get("tag_description"):
            tag.tag_description = tag_data["tag_description"]
        if tag_data.get("tag_type"):
            tag.tag_type = tag_data["tag_type"]
        if tag_data.get("tag_namespace"):
            tag.tag_namespace = tag_data["tag_namespace"]
        if tag_data.get("tag_slug"):
            tag.tag_slug = tag_data["tag_slug"]
    db.flush()

    if direct_tag_ids:
        _ = db.execute(delete(TagAncestorMap).where(TagAncestorMap.tag_id.in_(direct_tag_ids)))

    if ancestor_edges:
        db.bulk_insert_mappings(TagAncestorMap, ancestor_edges)

    if taggings:
        db.bulk_insert_mappings(
            CardTagging,
            [
                {
                    "id": tagging_data["id"],
                    "card_id": card_id,
                    "tag_id": tagging_data["tag_id"],
                    "foreign_key": tagging_data.get("foreign_key"),
                    "status": tagging_data.get("status"),
                    "tagging_type": tagging_data.get("tagging_type"),
                    "weight": tagging_data.get("weight"),
                    "annotation": tagging_data.get("annotation"),
                    "related_id": tagging_data.get("related_id"),
                }
                for tagging_data in taggings
            ],
        )

    if relationships:
        db.bulk_insert_mappings(
            CardRelationship,
            [
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
                for relationship in relationships
            ],
        )


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
        logger.info("Tagger GraphQL request failed for %s: %s", card_id, e)
        return FetchExtraction(FetchOutcome.FAILED)

    if resp.status_code == 429 or resp.status_code >= 500:
        return FetchExtraction(FetchOutcome.RESET_SESSION)

    if resp.status_code != 200:
        logger.info("Tagger returned HTTP %s for %s", resp.status_code, card_id)
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
            result = _tagger_graphql_once(
                session, csrf_token, card.set_code, card.collector_number, card.oracle_id
            )
        if result.outcome != FetchOutcome.RESET_SESSION:
            return result
        resets += 1
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


def _cards_needing_tag_fetch(db: Session, refresh_tags: bool) -> Sequence[Row[tuple[str, str, str, str]]]:
    return db.execute(_cards_needing_tag_fetch_query(refresh_tags)).all()


def _iter_cards_needing_tag_fetch(
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
    pending_commits = 0

    cards = list(_iter_cards_needing_tag_fetch(db, refresh_tags))
    rate_sem = threading.Semaphore(TAG_FETCH_CONCURRENCY)

    with ThreadPoolExecutor(max_workers=TAG_FETCH_CONCURRENCY, thread_name_prefix="tagger") as executor:
        # executor.map preserves input order and streams results — lets us write
        # to the DB in the same thread we already own the session on.
        futures = executor.map(
            lambda card: (card, _fetch_card_extraction(card, rate_sem)),
            cards,
        )

        for card, result in futures:
            processed += 1
            counts[result.outcome] += 1
            oracle_tag_count = 0
            relationship_count = 0

            if result.outcome == FetchOutcome.SUCCESS and result.extracted is not None:
                _replace_card_entities(db, card.oracle_id, result.extracted)
                oracle_tag_count = len(result.extracted["taggings"])
                relationship_count = len(result.extracted["relationships"])
                inserted_oracle_taggings += oracle_tag_count
                inserted_relationships += relationship_count
                pending_commits += 1
                if pending_commits >= TAG_FETCH_COMMIT_INTERVAL:
                    db.commit()
                    pending_commits = 0

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

    if pending_commits:
        db.commit()

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
