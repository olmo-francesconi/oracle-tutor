from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, cast

import requests
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..core.models import Card, CardRelationship, CardTagging, Tag, TagAncestorMap

logger = logging.getLogger("oracle_tutor_api.data")

TAGGER_BASE_URL = "https://tagger.scryfall.com"
TAGGER_GRAPHQL_URL = f"{TAGGER_BASE_URL}/graphql"
RATE_LIMIT_SLEEP = 0.1
SESSION_RESET_BACKOFF_SECONDS = 5.0
REQUEST_TIMEOUT_SECONDS = 10

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
        db.add(
            CardTagging(
                id=tagging_data["id"],
                card_id=card_id,
                tag_id=tagging_data["tag_id"],
                foreign_key=tagging_data.get("foreign_key"),
                status=tagging_data.get("status"),
                tagging_type=tagging_data.get("tagging_type"),
                weight=tagging_data.get("weight"),
                annotation=tagging_data.get("annotation"),
                related_id=tagging_data.get("related_id"),
            )
        )

    for relationship_data in relationships:
        db.add(
            CardRelationship(
                id=relationship_data["id"],
                card_id=card_id,
                foreign_key=relationship_data.get("foreign_key"),
                classifier=relationship_data.get("classifier"),
                classifier_inverse=relationship_data.get("classifier_inverse"),
                status=relationship_data.get("status"),
                relationship_type=relationship_data.get("relationship_type"),
                weight=relationship_data.get("weight"),
                annotation=relationship_data.get("annotation"),
                subject_remote_id=relationship_data.get("subject_remote_id"),
                subject_name=relationship_data.get("subject_name"),
                related_remote_id=relationship_data.get("related_remote_id"),
                related_name=relationship_data.get("related_name"),
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


def _cards_needing_tag_fetch(db: Session, refresh_tags: bool) -> list[Card]:
    query = db.query(Card).order_by(Card.id.asc())
    if refresh_tags:
        return query.all()

    return (
        query.outerjoin(CardTagging, CardTagging.card_id == Card.id)
        .filter(CardTagging.id.is_(None))
        .all()
    )


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

    logger.info(
        "Starting tag ingestion. mode=tagger_graphql cards=%d refresh_tags=%s",
        len(cards),
        refresh_tags,
    )

    for card in cards:
        if not card.scryfall_set or not card.collector_number:
            continue
        outcome = fetch_and_store_tags(
            db,
            tagger_session,
            csrf_token,
            card.scryfall_set,
            card.collector_number,
            card.id,
        )
        if outcome != FetchOutcome.RESET_SESSION:
            continue

        try:
            tagger_session.close()
        except Exception:
            logger.debug("Failed to close Tagger session cleanly.", exc_info=True)

        time.sleep(SESSION_RESET_BACKOFF_SECONDS)
        try:
            tagger_session, csrf_token = _create_tagger_session()
        except Exception as e:
            logger.warning("Tagger session re-bootstrap failed after retryable response: %s", e)
            return

        retry_outcome = fetch_and_store_tags(
            db,
            tagger_session,
            csrf_token,
            card.scryfall_set,
            card.collector_number,
            card.id,
        )
        if retry_outcome == FetchOutcome.RESET_SESSION:
            logger.warning("Tagger still returning retryable failures after session reset; stopping tag ingestion.")
            return

    try:
        tagger_session.close()
    except Exception:
        logger.debug("Failed to close Tagger session cleanly at end of run.", exc_info=True)
