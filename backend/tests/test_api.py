from ot_backend.api.main import _CARD_TYPE_MAP, _FORMAT_MAP, _parse_code_filter
from ot_backend.core.database import SessionLocal
from ot_backend.core.models import AnalyticsEvent, ClientErrorEvent


def test_root(client):
    res = client.get("/")
    assert res.status_code == 200
    assert res.json() == {"service": "oracle-tutor-api"}


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_openapi(client):
    res = client.get("/openapi.json")
    assert res.status_code == 200
    data = res.json()
    assert data["info"]["title"] == "oracle-tutor api"


def test_search(client):
    res = client.get("/search", params={"q": "sho", "limit": 10})
    assert res.status_code == 200
    names = [x["name"] for x in res.json()]
    assert "Shock" in names


def test_oracle_samples_include_terms_from_keywords_and_ability_words(client):
    res = client.get("/oracle-samples", params={"n": 60})
    assert res.status_code == 200
    data = res.json()
    assert "texts" in data
    assert "terms" in data
    assert "Deathtouch" in data["terms"]
    assert "Trample" in data["terms"]
    assert "Vigilance" in data["terms"]
    assert "Landfall" in data["terms"]


def test_search_returns_multiple_faces_for_multi_face_name_matches(client):
    res = client.get("/search", params={"q": "aang", "limit": 10})
    assert res.status_code == 200
    assert res.json() == [
        {
            "name": "Aang, at the Crossroads",
            "similarity": 1.0,
            "rank": 8,
            "oracle_id": "o8",
            "scryfall_id": "s8",
            "face_ix": 0,
            "image_side": "front",
        },
        {
            "name": "Aang, Destined Savior",
            "similarity": 1.0,
            "rank": 8,
            "oracle_id": "o8",
            "scryfall_id": "s8",
            "face_ix": 1,
            "image_side": "back",
        },
    ]


def test_similar_cards_includes_face_index(client, monkeypatch):
    class FakeSemanticIndex:
        def similar_to_face(self, *_args, **_kwargs):
            return [(("o2", 0), 0.95)]

    monkeypatch.setattr("ot_backend.api.main._get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"oracle_id": "o1", "face_ix": 0, "limit": 10})
    assert res.status_code == 200
    assert res.json() == {
        "items": [
            {
                "oracle_id": "o2",
                "scryfall_id": "s2",
                "face_ix": 0,
                "image_side": "front",
                "name": "Shock",
                "card_name": "Shock",
                "similarity": 0.95,
                "rank": 2,
                "type_line": "Instant",
                "mana_cost": None,
                "oracle_text": "Shock deals 2 damage to any target.",
                "power": None,
                "toughness": None,
                "colors": ["R"],
                "layout": "normal",
                "rarity": "common",
                "legalities": {},
                "uniqueness": None,
                "border_color": None,
                "set_code": "tst",
            }
        ],
        "has_more": False,
    }


def test_similar_cards_uses_shared_front_image_side_for_split_faces(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return [(("o6", 1), 0.91)]

    monkeypatch.setattr("ot_backend.api.main._get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "tap draw", "limit": 10})
    assert res.status_code == 200
    assert res.json()["items"][0]["face_ix"] == 1
    assert res.json()["items"][0]["image_side"] == "front"
    assert res.json()["items"][0]["name"] == "Ice"


def test_similar_cards_uses_back_image_side_for_double_faced_back_face(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return [(("o7", 1), 0.89)]

    monkeypatch.setattr("ot_backend.api.main._get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "werewolf", "limit": 10})
    assert res.status_code == 200
    assert res.json()["items"][0]["face_ix"] == 1
    assert res.json()["items"][0]["image_side"] == "back"
    assert res.json()["items"][0]["name"] == "Moonrage Brute"


def test_similar_cards_sets_has_more_when_more_results_exist(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return [(("o2", 0), 0.95), (("o1", 0), 0.9)]

    monkeypatch.setattr("ot_backend.api.main._get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "shock", "limit": 1, "offset": 0})
    assert res.status_code == 200
    assert len(res.json()["items"]) == 1
    assert res.json()["has_more"] is True


def test_similar_cards_sets_has_more_false_on_last_page(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return [(("o2", 0), 0.95), (("o1", 0), 0.9)]

    monkeypatch.setattr("ot_backend.api.main._get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "shock", "limit": 1, "offset": 1})
    assert res.status_code == 200
    assert len(res.json()["items"]) == 1
    assert res.json()["has_more"] is False


def test_compact_type_and_format_filters_decode_to_backend_values():
    assert _parse_code_filter("is", _CARD_TYPE_MAP, "card type") == ["instant", "sorcery"]
    assert _parse_code_filter("ml", _FORMAT_MAP, "format") == ["modern", "legacy"]


def test_similar_cards_rejects_duplicate_compact_format_codes(client):
    res = client.get("/similar-cards", params={"q": "shock", "format": "mm"})

    assert res.status_code == 422


def test_data_endpoints_return_503_while_schema_migrating(client, monkeypatch):
    monkeypatch.setattr("ot_backend.api.main._schema_ready", False)
    monkeypatch.setattr("ot_backend.api.main.wait_for_migration_ready", lambda **_: False)

    res = client.get("/search", params={"q": "shock"})
    assert res.status_code == 503


def test_client_error_telemetry_is_persisted(client):
    res = client.post(
        "/telemetry/client-error",
        json={
            "message": "render exploded",
            "name": "TypeError",
            "stack": "TypeError: render exploded",
            "context": {
                "source": "react.error-boundary",
                "route": "/search",
            },
            "url": "https://example.test/search?q=bolt",
            "userAgent": "Vitest Browser",
            "timestamp": "2026-03-28T12:00:00Z",
        },
    )

    assert res.status_code == 202
    assert res.json() == {"accepted": True}

    with SessionLocal() as db:
        event = db.query(ClientErrorEvent).one()

    assert event.error_name == "TypeError"
    assert event.message == "render exploded"
    assert event.source == "react.error-boundary"
    assert event.context == {
        "source": "react.error-boundary",
        "route": "/search",
    }


def test_analytics_telemetry_is_persisted(client):
    res = client.post(
        "/telemetry/analytics",
        json={
            "event": "filters_cleared",
            "props": {
                "previousKeys": ["format"],
                "queryLength": 5,
            },
            "url": "https://example.test/search?q=bolt",
            "userAgent": "Vitest Browser",
            "timestamp": "2026-03-28T12:00:00Z",
        },
    )

    assert res.status_code == 202
    assert res.json() == {"accepted": True}

    with SessionLocal() as db:
        event = db.query(AnalyticsEvent).one()

    assert event.event_name == "filters_cleared"
    assert event.props == {
        "previousKeys": ["format"],
        "queryLength": 5,
    }


def test_analytics_telemetry_rejects_invalid_event_name(client):
    res = client.post(
        "/telemetry/analytics",
        json={
            "event": "mystery_event",
            "props": {},
            "url": "https://example.test/search",
            "userAgent": "Vitest Browser",
        },
    )

    assert res.status_code == 422


def test_client_error_telemetry_rejects_oversized_context(client):
    res = client.post(
        "/telemetry/client-error",
        json={
            "message": "render exploded",
            "name": "TypeError",
            "context": {
                "payload": "x" * 9000,
            },
            "url": "https://example.test/search",
            "userAgent": "Vitest Browser",
        },
    )

    assert res.status_code == 413


def test_search_rejects_overlong_query(client):
    res = client.get("/search", params={"q": "x" * 201})

    assert res.status_code == 422


def test_similar_cards_rejects_overlong_query(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return []

    monkeypatch.setattr("ot_backend.api.main._get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "x" * 201})

    assert res.status_code == 422


def test_telemetry_rejects_oversized_request_body(client):
    res = client.post(
        "/telemetry/client-error",
        content=b"x" * 40000,
        headers={"content-type": "application/json"},
    )

    assert res.status_code == 413


def test_rejects_disallowed_host_header(client):
    res = client.get("/health", headers={"host": "evil.example"})

    assert res.status_code == 400
