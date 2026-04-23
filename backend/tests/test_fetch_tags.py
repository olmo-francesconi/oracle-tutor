from __future__ import annotations

from typing import cast

import requests

from ot_backend.core.database import SessionLocal
from ot_backend.core.db_init import init_db
from ot_backend.core.models import Card, CardRaw, CardRelationship, CardTagging, Tag, TagAncestorMap
from ot_backend.ingest.fetch_tags import (
    FetchOutcome,
    _cards_needing_tag_fetch,
    _extract_card_entities,
    _replace_card_entities,
    _tagger_graphql_once,
)

SAMPLE_TAGGER_PAYLOAD = {
    "data": {
        "card": {
            "name": "Hallowed Fountain",
            "taggings": [
                {
                    "id": "tagging-art-1",
                    "annotation": None,
                    "status": "GOOD_STANDING",
                    "type": "TAGGING",
                    "weight": "MEDIAN",
                    "relatedId": None,
                    "foreignKey": "illustrationId",
                    "tag": {
                        "id": "tag-art-1",
                        "name": "cityscape",
                        "description": "A city view.",
                        "type": "ILLUSTRATION_TAG",
                        "namespace": "artwork",
                        "slug": "cityscape",
                        "ancestorTags": [],
                    },
                },
                {
                    "id": "tagging-card-1",
                    "annotation": None,
                    "status": "GOOD_STANDING",
                    "type": "TAGGING",
                    "weight": "MEDIAN",
                    "relatedId": None,
                    "foreignKey": "oracleId",
                    "tag": {
                        "id": "tag-card-1",
                        "name": "shockland",
                        "description": "Dual lands that can enter untapped for 2 life.",
                        "type": "ORACLE_CARD_TAG",
                        "namespace": "card",
                        "slug": "shockland",
                        "ancestorTags": [
                            {
                                "id": "tag-card-parent-1",
                                "name": "dual land",
                                "description": None,
                                "type": "ORACLE_CARD_TAG",
                                "namespace": "card",
                                "slug": "dual-land",
                            }
                        ],
                    },
                },
            ],
            "relationships": [
                {
                    "id": "rel-art-1",
                    "annotation": None,
                    "classifier": "SAME_ART",
                    "classifierInverse": "SAME_ART",
                    "foreignKey": "illustrationId",
                    "relatedId": "other-printing-1",
                    "relatedName": "Hallowed Fountain Showcase",
                    "subjectId": "printing-card-1",
                    "subjectName": "Hallowed Fountain",
                    "status": "GOOD_STANDING",
                    "type": "RELATIONSHIP",
                    "weight": "MEDIAN",
                },
                {
                    "id": "rel-1",
                    "annotation": None,
                    "classifier": "BETTER_THAN",
                    "classifierInverse": "WORSE_THAN",
                    "foreignKey": "oracleId",
                    "relatedId": "other-card-1",
                    "relatedName": "Coastal Tower",
                    "subjectId": "oracle-card-1",
                    "subjectName": "Hallowed Fountain",
                    "status": "GOOD_STANDING",
                    "type": "RELATIONSHIP",
                    "weight": "MEDIAN",
                }
            ],
        }
    }
}


def _make_card_raw(*, scryfall_id: str, oracle_id: str, name: str, collector_number: str) -> CardRaw:
    return CardRaw(
        id=scryfall_id,
        oracle_id=oracle_id,
        name=name,
        lang="en",
        layout="normal",
        color_identity=["W", "U"],
        keywords=[],
        legalities={},
        rarity="rare",
        set_code="rvr",
        set_id="set-rvr",
        set_name="Ravnica Remastered",
        set_type="expansion",
        collector_number=collector_number,
        games=["paper"],
        finishes=["nonfoil"],
    )


def test_extract_card_entities_preserves_direct_tags_ancestors_and_relationships() -> None:
    extracted = _extract_card_entities(SAMPLE_TAGGER_PAYLOAD)

    assert {tag["id"] for tag in extracted["tags"]} == {"tag-card-1", "tag-card-parent-1"}
    assert {(tagging["id"], tagging["foreign_key"]) for tagging in extracted["taggings"]} == {
        ("tagging-card-1", "oracleId"),
    }
    assert extracted["ancestor_edges"] == [{"tag_id": "tag-card-1", "ancestor_tag_id": "tag-card-parent-1"}]
    assert extracted["relationships"] == [
        {
            "id": "rel-1",
            "foreign_key": "oracleId",
            "classifier": "BETTER_THAN",
            "classifier_inverse": "WORSE_THAN",
            "status": "GOOD_STANDING",
            "relationship_type": "RELATIONSHIP",
            "weight": "MEDIAN",
            "annotation": None,
            "subject_remote_id": "oracle-card-1",
            "subject_name": "Hallowed Fountain",
            "related_remote_id": "other-card-1",
            "related_name": "Coastal Tower",
        }
    ]


def test_replace_card_entities_persists_only_oracle_scoped_rows() -> None:
    init_db()
    extracted = _extract_card_entities(SAMPLE_TAGGER_PAYLOAD)

    with SessionLocal() as db:
        db.query(CardRelationship).delete()
        db.query(CardTagging).delete()
        db.query(TagAncestorMap).delete()
        db.query(Tag).delete()
        db.query(Card).delete()
        db.query(CardRaw).delete()
        db.add(
            _make_card_raw(
                scryfall_id="scryfall-card-1",
                oracle_id="card-1",
                name="Hallowed Fountain",
                collector_number="404",
            )
        )
        db.add(
            Card(
                oracle_id="card-1",
                scryfall_id="scryfall-card-1",
                name="Hallowed Fountain",
                layout="normal",
                rarity="rare",
                legalities={},
                color_identity=["W", "U"],
            )
        )
        db.commit()

        _replace_card_entities(db, "card-1", extracted)

        tags = {tag.id: tag for tag in db.query(Tag).all()}
        assert set(tags) == {"tag-card-1", "tag-card-parent-1"}
        assert tags["tag-card-1"].tag_namespace == "card"

        taggings = {tagging.id: tagging for tagging in db.query(CardTagging).all()}
        assert set(taggings) == {"tagging-card-1"}
        assert taggings["tagging-card-1"].foreign_key == "oracleId"

        ancestor_edges = {
            (edge.tag_id, edge.ancestor_tag_id)
            for edge in db.query(TagAncestorMap).all()
        }
        assert ancestor_edges == {("tag-card-1", "tag-card-parent-1")}

        relationships = db.query(CardRelationship).all()
        assert len(relationships) == 1
        assert relationships[0].classifier == "BETTER_THAN"
        assert relationships[0].related_name == "Coastal Tower"


def test_replace_card_entities_removes_existing_artwork_rows_on_refresh() -> None:
    init_db()
    extracted = _extract_card_entities(SAMPLE_TAGGER_PAYLOAD)

    with SessionLocal() as db:
        db.query(CardRelationship).delete()
        db.query(CardTagging).delete()
        db.query(TagAncestorMap).delete()
        db.query(Tag).delete()
        db.query(Card).delete()
        db.query(CardRaw).delete()
        db.add(
            _make_card_raw(
                scryfall_id="scryfall-card-1",
                oracle_id="card-1",
                name="Hallowed Fountain",
                collector_number="404",
            )
        )
        db.add(
            Card(
                oracle_id="card-1",
                scryfall_id="scryfall-card-1",
                name="Hallowed Fountain",
                layout="normal",
                rarity="rare",
                legalities={},
                color_identity=["W", "U"],
            )
        )
        db.add_all(
            [
                Tag(id="tag-art-1", tag_name="cityscape", tag_namespace="artwork"),
                Tag(id="tag-card-1", tag_name="shockland", tag_namespace="card"),
                CardTagging(id="tagging-art-1", card_id="card-1", tag_id="tag-art-1", foreign_key="illustrationId"),
                CardRelationship(
                    id="rel-art-1",
                    card_id="card-1",
                    foreign_key="illustrationId",
                    classifier="SAME_ART",
                    classifier_inverse="SAME_ART",
                    relationship_type="RELATIONSHIP",
                    related_remote_id="other-printing-1",
                    related_name="Hallowed Fountain Showcase",
                ),
            ]
        )
        db.commit()

        _replace_card_entities(db, "card-1", extracted)

        taggings = {(tagging.id, tagging.foreign_key) for tagging in db.query(CardTagging).all()}
        assert taggings == {("tagging-card-1", "oracleId")}

        relationships = {(relationship.id, relationship.foreign_key) for relationship in db.query(CardRelationship).all()}
        assert relationships == {("rel-1", "oracleId")}


def test_cards_needing_tag_fetch_only_returns_cards_without_taggings() -> None:
    init_db()
    with SessionLocal() as db:
        db.query(CardRelationship).delete()
        db.query(CardTagging).delete()
        db.query(TagAncestorMap).delete()
        db.query(Tag).delete()
        db.query(Card).delete()
        db.query(CardRaw).delete()
        db.add_all(
            [
                _make_card_raw(scryfall_id="scryfall-card-1", oracle_id="card-1", name="Tagged Card", collector_number="404"),
                _make_card_raw(scryfall_id="scryfall-card-2", oracle_id="card-2", name="Untagged Card", collector_number="405"),
                Card(oracle_id="card-1", scryfall_id="scryfall-card-1", name="Tagged Card", layout="normal", rarity="rare", legalities={}, color_identity=["W", "U"]),
                Card(oracle_id="card-2", scryfall_id="scryfall-card-2", name="Untagged Card", layout="normal", rarity="rare", legalities={}, color_identity=["W", "U"]),
            ]
        )
        db.add(Tag(id="tag-card-1", tag_name="shockland", tag_namespace="card"))
        db.add(CardTagging(id="tagging-card-1", card_id="card-1", tag_id="tag-card-1", foreign_key="oracleId"))
        db.commit()

        assert [card.oracle_id for card in _cards_needing_tag_fetch(db, refresh_tags=False)] == ["card-2"]
        assert [card.oracle_id for card in _cards_needing_tag_fetch(db, refresh_tags=True)] == ["card-1", "card-2"]


def test_tagger_graphql_once_requests_session_reset_on_retryable_status() -> None:
    init_db()

    class DummyResponse:
        status_code = 429
        text = "rate limited"

        def json(self):
            return {}

    class DummySession:
        def post(self, *args: object, **kwargs: object) -> DummyResponse:
            return DummyResponse()

    result = _tagger_graphql_once(
        cast(requests.Session, cast(object, DummySession())),
        "csrf-token",
        "rvr",
        "404",
        "card-1",
    )

    assert result.outcome == FetchOutcome.RESET_SESSION
    assert result.extracted is None
