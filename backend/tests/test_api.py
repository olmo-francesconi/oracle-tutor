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
    assert res.json() == [
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
        }
    ]


def test_similar_cards_uses_shared_front_image_side_for_split_faces(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return [(("o6", 1), 0.91)]

    monkeypatch.setattr("ot_backend.api.main._get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "tap draw", "limit": 10})
    assert res.status_code == 200
    assert res.json()[0]["face_ix"] == 1
    assert res.json()[0]["image_side"] == "front"
    assert res.json()[0]["name"] == "Ice"


def test_similar_cards_uses_back_image_side_for_double_faced_back_face(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return [(("o7", 1), 0.89)]

    monkeypatch.setattr("ot_backend.api.main._get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "werewolf", "limit": 10})
    assert res.status_code == 200
    assert res.json()[0]["face_ix"] == 1
    assert res.json()[0]["image_side"] == "back"
    assert res.json()[0]["name"] == "Moonrage Brute"


def test_data_endpoints_return_503_while_schema_migrating(client, monkeypatch):
    monkeypatch.setattr("ot_backend.api.main._schema_ready", False)
    monkeypatch.setattr("ot_backend.api.main.wait_for_migration_ready", lambda **_: False)

    res = client.get("/search", params={"q": "shock"})
    assert res.status_code == 503
