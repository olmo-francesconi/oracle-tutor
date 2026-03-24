from __future__ import annotations

import logging
import time
from enum import Enum
from collections.abc import Sequence
from typing import Any, cast

import requests
from sqlalchemy import Row, delete, select
from sqlalchemy.orm import Session

from ..core.models import Card, CardRaw, CardRelationship, CardTagging, Tag, TagAncestorMap

logger = logging.getLogger("ot_backend.ingest")

TAGGER_BASE_URL = "https://tagger.scryfall.com"
TAGGER_GRAPHQL_URL = f"{TAGGER_BASE_URL}/graphql"
RATE_LIMIT_SLEEP = 0.1
SESSION_RESET_BACKOFF_SECONDS = 5.0
REQUEST_TIMEOUT_SECONDS = 10
MAX_SESSION_RESETS: int = 5

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


class FetchOutcome(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    RESET_SESSION = "reset_session"


def _normalize_tag_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    tag = value.strip()
    return tag or None


def _normalize_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _extract_card_entities(payload: Any) -> dict[str, list[dict[str, str | None]]]:
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

    tags_by_id: dict[str, dict[str, str | None]] = {}
    direct_taggings: list[dict[str, str | None]] = []
    ancestor_edges: set[tuple[str, str]] = set()
    extracted_relationships: list[dict[str, str | None]] = []

    def upsert_tag(raw_tag: Any) -> str | None:
        if not isinstance(raw_tag, dict):
            return None
        tag_id = _normalize_tag_value(raw_tag.get("id"))
        tag_name = _normalize_tag_value(raw_tag.get("name"))
        if not tag_id or not tag_name:
            return None
        existing = tags_by_id.get(tag_id, {})
        tags_by_id[tag_id] = {
            "id": tag_id,
            "tag_name": tag_name,
            "tag_description": _normalize_optional_text(raw_tag.get("description")) or existing.get("tag_description"),
            "tag_type": _normalize_optional_text(raw_tag.get("type")) or existing.get("tag_type"),
            "tag_namespace": _normalize_optional_text(raw_tag.get("namespace")) or existing.get("tag_namespace"),
            "tag_slug": _normalize_optional_text(raw_tag.get("slug")) or existing.get("tag_slug"),
        }
        return tag_id

    for tagging in taggings:
        if not isinstance(tagging, dict):
            continue
        raw_tag = tagging.get("tag")
        if not isinstance(raw_tag, dict):
            continue
        tag = cast(dict[str, Any], raw_tag)
        tag_id = upsert_tag(tag)
        tagging_id = _normalize_tag_value(tagging.get("id"))
        if not tagging_id or not tag_id:
            continue
        direct_taggings.append(
            {
                "id": tagging_id,
                "tag_id": tag_id,
                "foreign_key": _normalize_optional_text(tagging.get("foreignKey")),
                "status": _normalize_optional_text(tagging.get("status")),
                "tagging_type": _normalize_optional_text(tagging.get("type")),
                "weight": _normalize_optional_text(tagging.get("weight")),
                "annotation": _normalize_optional_text(tagging.get("annotation")),
                "related_id": _normalize_optional_text(tagging.get("relatedId")),
            }
        )
        for ancestor_tag in tag.get("ancestorTags") or []:
            ancestor_id = upsert_tag(ancestor_tag)
            if ancestor_id and ancestor_id != tag_id:
                ancestor_edges.add((tag_id, ancestor_id))

    for relationship in relationships:
        if not isinstance(relationship, dict):
            continue
        relationship_id = _normalize_tag_value(relationship.get("id"))
        if not relationship_id:
            continue
        extracted_relationships.append(
            {
                "id": relationship_id,
                "foreign_key": _normalize_optional_text(relationship.get("foreignKey")),
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


def _upsert_tag(db: Session, tag_data: dict[str, str | None]) -> None:
    tag_id = tag_data["id"]
    tag = db.get(Tag, tag_id)
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
        return

    tag.tag_name = tag_data["tag_name"] or tag.tag_name
    if tag_data.get("tag_description"):
        tag.tag_description = tag_data["tag_description"]
    if tag_data.get("tag_type"):
        tag.tag_type = tag_data["tag_type"]
    if tag_data.get("tag_namespace"):
        tag.tag_namespace = tag_data["tag_namespace"]
    if tag_data.get("tag_slug"):
        tag.tag_slug = tag_data["tag_slug"]


def _replace_card_entities(db: Session, card_id: str, extracted: dict[str, list[dict[str, str | None]]]) -> None:
    tags = extracted["tags"]
    taggings = extracted["taggings"]
    ancestor_edges = extracted["ancestor_edges"]
    relationships = extracted["relationships"]
    direct_tag_ids = sorted(
        tagging["tag_id"]
        for tagging in taggings
        if isinstance(tagging.get("tag_id"), str) and tagging["tag_id"]
    )

    db.execute(delete(CardRelationship).where(CardRelationship.card_id == card_id))
    db.execute(delete(CardTagging).where(CardTagging.card_id == card_id))

    for tag_data in tags:
        _upsert_tag(db, tag_data)
    db.flush()

    if direct_tag_ids:
        db.execute(delete(TagAncestorMap).where(TagAncestorMap.tag_id.in_(direct_tag_ids)))

    for edge in ancestor_edges:
        db.add(TagAncestorMap(tag_id=edge["tag_id"], ancestor_tag_id=edge["ancestor_tag_id"]))

    for tagging_data in taggings:
        foreign_key = tagging_data.get("foreign_key")
        db.merge(
            CardTagging(
                id=tagging_data["id"],
                card_id=card_id,
                tag_id=tagging_data["tag_id"],
                foreign_key=foreign_key,
                status=tagging_data.get("status"),
                tagging_type=tagging_data.get("tagging_type"),
                weight=tagging_data.get("weight"),
                annotation=tagging_data.get("annotation"),
                related_id=tagging_data.get("related_id"),
            )
        )

    for r in relationships:
        db.merge(
            CardRelationship(
                id=r["id"],
                card_id=card_id,
                foreign_key=r.get("foreign_key"),
                classifier=r.get("classifier"),
                classifier_inverse=r.get("classifier_inverse"),
                status=r.get("status"),
                relationship_type=r.get("relationship_type"),
                weight=r.get("weight"),
                annotation=r.get("annotation"),
                subject_remote_id=r.get("subject_remote_id"),
                subject_name=r.get("subject_name"),
                related_remote_id=r.get("related_remote_id"),
                related_name=r.get("related_name"),
            )
        )
    db.commit()


def fetch_and_store_tags(
    db: Session,
    session: requests.Session,
    csrf_token: str,
    scryfall_set: str,
    collector_number: str,
    card_id: str,
) -> FetchOutcome:
    if not scryfall_set or not collector_number:
        return FetchOutcome.FAILED

    try:
        resp = session.post(
            TAGGER_GRAPHQL_URL,
            headers={
                "X-CSRF-Token": csrf_token,
                "Content-Type": "application/json",
            },
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
        return FetchOutcome.FAILED

    if resp.status_code == 429 or resp.status_code >= 500:
        logger.warning(
            "Tagger returned retryable HTTP %s for %s; rotating session.",
            resp.status_code,
            card_id,
        )
        return FetchOutcome.RESET_SESSION

    if resp.status_code != 200:
        logger.info("Tagger returned HTTP %s for %s", resp.status_code, card_id)
        return FetchOutcome.FAILED

    try:
        payload = resp.json()
    except Exception as e:
        logger.info("Tagger JSON parse failed for %s: %s", card_id, e)
        return FetchOutcome.FAILED

    if payload.get("errors"):
        logger.info("Tagger GraphQL errors for %s: %s", card_id, payload["errors"])
        return FetchOutcome.FAILED

    extracted = _extract_card_entities(payload)
    _replace_card_entities(db, card_id, extracted)
    time.sleep(RATE_LIMIT_SLEEP)
    return FetchOutcome.SUCCESS


def _cards_needing_tag_fetch(db: Session, refresh_tags: bool) -> Sequence[Row[tuple[str, str, str]]]:
    query = (
        select(Card.oracle_id, CardRaw.set_code, CardRaw.collector_number)
        .join(CardRaw, CardRaw.id == Card.scryfall_id)
        .order_by(Card.oracle_id.asc())
    )
    if not refresh_tags:
        query = (
            query.outerjoin(CardTagging, CardTagging.card_id == Card.oracle_id)
            .where(CardTagging.id.is_(None))
        )
    return db.execute(query).all()


def run_fetch_tags(db: Session, *, refresh_tags: bool = False) -> None:
    cards = _cards_needing_tag_fetch(db, refresh_tags)
    if not cards:
        logger.info("No cards require Tagger refresh. refresh_tags=%s", refresh_tags)
        return

    try:
        tagger_session, csrf_token = _create_tagger_session()
    except Exception as e:
        logger.warning("Tagger session bootstrap failed; skipping community tag ingestion: %s", e)
        return

    total = len(cards)
    logger.info(
        "Starting tag ingestion. mode=tagger_graphql cards=%d refresh_tags=%s",
        total,
        refresh_tags,
    )

    counts = {FetchOutcome.SUCCESS: 0, FetchOutcome.FAILED: 0, FetchOutcome.RESET_SESSION: 0}
    LOG_INTERVAL = 100

    for i, card in enumerate(cards, start=1):
        if not card.set_code or not card.collector_number:
            counts[FetchOutcome.FAILED] += 1
            continue
        outcome = fetch_and_store_tags(
            db,
            tagger_session,
            csrf_token,
            card.set_code,
            card.collector_number,
            card.oracle_id,
        )
        counts[outcome] += 1

        if i % LOG_INTERVAL == 0 or i == total:
            logger.info(
                "Tag ingestion progress: %d/%d  success=%d failed=%d session_resets=%d",
                i, total,
                counts[FetchOutcome.SUCCESS],
                counts[FetchOutcome.FAILED],
                counts[FetchOutcome.RESET_SESSION],
            )

        if outcome != FetchOutcome.RESET_SESSION:
            continue

        session_resets = 0
        while outcome == FetchOutcome.RESET_SESSION:
            session_resets += 1
            if session_resets >= MAX_SESSION_RESETS:
                logger.error(
                    "Tagger rate limit: exceeded max session resets for card %s/%s, skipping.",
                    card.set_code,
                    card.collector_number,
                )
                break

            try:
                tagger_session.close()
            except Exception:
                logger.debug("Failed to close Tagger session cleanly.", exc_info=True)

            time.sleep(SESSION_RESET_BACKOFF_SECONDS)
            try:
                tagger_session, csrf_token = _create_tagger_session()
            except Exception as e:
                logger.warning("Tagger session re-bootstrap failed after retryable response: %s", e)
                break

            outcome = fetch_and_store_tags(
                db,
                tagger_session,
                csrf_token,
                card.set_code,
                card.collector_number,
                card.oracle_id,
            )
            if outcome == FetchOutcome.RESET_SESSION:
                counts[FetchOutcome.RESET_SESSION] += 1

    try:
        tagger_session.close()
    except Exception:
        logger.debug("Failed to close Tagger session cleanly at end of run.", exc_info=True)

    tag_count = db.query(Tag).count()
    tagging_count = db.query(CardTagging).count()
    relationship_count = db.query(CardRelationship).count()
    logger.info(
        "Tag ingestion complete. success=%d failed=%d  db: tags=%d taggings=%d relationships=%d",
        counts[FetchOutcome.SUCCESS],
        counts[FetchOutcome.FAILED],
        tag_count,
        tagging_count,
        relationship_count,
    )
