from __future__ import annotations

from oracle_tutor_api.core.database import SessionLocal
from oracle_tutor_api.core.db_init import init_db
from oracle_tutor_api.core.models import Card, CardRelationship, CardTagging, Tag, TagAncestorMap
from oracle_tutor_api.worker.fetch_tags import FetchOutcome, _cards_needing_tag_fetch, _extract_card_entities, _replace_card_entities, fetch_and_store_tags


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


def test_extract_card_entities_preserves_direct_tags_ancestors_and_relationships() -> None:
    extracted = _extract_card_entities(SAMPLE_TAGGER_PAYLOAD)

    assert {tag["id"] for tag in extracted["tags"]} == {"tag-art-1", "tag-card-1", "tag-card-parent-1"}
    assert {(tagging["id"], tagging["foreign_key"]) for tagging in extracted["taggings"]} == {
        ("tagging-art-1", "illustrationId"),
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


def test_replace_card_entities_persists_full_tagger_shape() -> None:
    init_db()
    extracted = _extract_card_entities(SAMPLE_TAGGER_PAYLOAD)

    with SessionLocal() as db:
        db.query(CardRelationship).delete()
        db.query(CardTagging).delete()
        db.query(TagAncestorMap).delete()
        db.query(Tag).delete()
        db.query(Card).delete()
        db.add(
            Card(
                id="card-1",
                name="Hallowed Fountain",
                scryfall_set="rvr",
                collector_number="404",
                layout="normal",
                rarity="rare",
                legalities={},
                color_identity=["W", "U"],
            )
        )
        db.commit()

        _replace_card_entities(db, "card-1", extracted)

        tags = {tag.id: tag for tag in db.query(Tag).all()}
        assert set(tags) == {"tag-art-1", "tag-card-1", "tag-card-parent-1"}
        assert tags["tag-card-1"].tag_namespace == "card"
        assert tags["tag-art-1"].tag_namespace == "artwork"

        taggings = {tagging.id: tagging for tagging in db.query(CardTagging).all()}
        assert set(taggings) == {"tagging-art-1", "tagging-card-1"}
        assert taggings["tagging-card-1"].foreign_key == "oracleId"
        assert taggings["tagging-art-1"].foreign_key == "illustrationId"

        ancestor_edges = {
            (edge.tag_id, edge.ancestor_tag_id)
            for edge in db.query(TagAncestorMap).all()
        }
        assert ancestor_edges == {("tag-card-1", "tag-card-parent-1")}

        relationships = db.query(CardRelationship).all()
        assert len(relationships) == 1
        assert relationships[0].classifier == "BETTER_THAN"
        assert relationships[0].related_name == "Coastal Tower"


def test_cards_needing_tag_fetch_only_returns_cards_without_taggings() -> None:
    init_db()
    with SessionLocal() as db:
        db.query(CardRelationship).delete()
        db.query(CardTagging).delete()
        db.query(TagAncestorMap).delete()
        db.query(Tag).delete()
        db.query(Card).delete()
        db.add_all(
            [
                Card(id="card-1", name="Tagged Card", scryfall_set="rvr", collector_number="404", layout="normal", rarity="rare", legalities={}, color_identity=["W", "U"]),
                Card(id="card-2", name="Untagged Card", scryfall_set="rvr", collector_number="405", layout="normal", rarity="rare", legalities={}, color_identity=["W", "U"]),
            ]
        )
        db.add(Tag(id="tag-card-1", tag_name="shockland", tag_namespace="card"))
        db.add(CardTagging(id="tagging-card-1", card_id="card-1", tag_id="tag-card-1", foreign_key="oracleId"))
        db.commit()

        assert [card.id for card in _cards_needing_tag_fetch(db, refresh_tags=False)] == ["card-2"]
        assert [card.id for card in _cards_needing_tag_fetch(db, refresh_tags=True)] == ["card-1", "card-2"]


def test_fetch_and_store_tags_requests_session_reset_on_retryable_status() -> None:
    init_db()

    class DummyResponse:
        status_code = 429

        def json(self):
            return {}

    class DummySession:
        def post(self, *args, **kwargs):
            return DummyResponse()

    with SessionLocal() as db:
        outcome = fetch_and_store_tags(
            db,
            DummySession(),  # type: ignore[arg-type]
            "csrf-token",
            "rvr",
            "404",
            "card-1",
        )

    assert outcome == FetchOutcome.RESET_SESSION
