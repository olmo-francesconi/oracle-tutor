from ot_backend.api.routers.search import _CARD_TYPE_MAP, _FORMAT_MAP, _parse_code_filter


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
            "card_name": "Aang, at the Crossroads // Aang, Destined Savior",
            "similarity": 1.0,
            "rank": 8,
            "oracle_id": "o8",
            "scryfall_id": "s8",
            "face_ix": 0,
            "image_side": "front",
        },
        {
            "name": "Aang, Destined Savior",
            "card_name": "Aang, at the Crossroads // Aang, Destined Savior",
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

    monkeypatch.setattr("ot_backend.api._semantic_index.get_semantic_index", lambda: FakeSemanticIndex())

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

    monkeypatch.setattr("ot_backend.api._semantic_index.get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "tap draw", "limit": 10})
    assert res.status_code == 200
    assert res.json()["items"][0]["face_ix"] == 1
    assert res.json()["items"][0]["image_side"] == "front"
    assert res.json()["items"][0]["name"] == "Ice"


def test_similar_cards_uses_back_image_side_for_double_faced_back_face(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return [(("o7", 1), 0.89)]

    monkeypatch.setattr("ot_backend.api._semantic_index.get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "werewolf", "limit": 10})
    assert res.status_code == 200
    assert res.json()["items"][0]["face_ix"] == 1
    assert res.json()["items"][0]["image_side"] == "back"
    assert res.json()["items"][0]["name"] == "Moonrage Brute"


def test_similar_cards_sets_has_more_when_more_results_exist(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return [(("o2", 0), 0.95), (("o1", 0), 0.9)]

    monkeypatch.setattr("ot_backend.api._semantic_index.get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "shock", "limit": 1, "offset": 0})
    assert res.status_code == 200
    assert len(res.json()["items"]) == 1
    assert res.json()["has_more"] is True


def test_similar_cards_sets_has_more_false_on_last_page(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return [(("o2", 0), 0.95), (("o1", 0), 0.9)]

    monkeypatch.setattr("ot_backend.api._semantic_index.get_semantic_index", lambda: FakeSemanticIndex())

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
    monkeypatch.setattr("ot_backend.api._ensure_schema_ready._schema_ready", False)
    monkeypatch.setattr("ot_backend.api._ensure_schema_ready.wait_for_migration_ready", lambda **_: False)

    res = client.get("/search", params={"q": "shock"})
    assert res.status_code == 503


def test_search_rejects_overlong_query(client):
    res = client.get("/search", params={"q": "x" * 201})

    assert res.status_code == 422


def test_similar_cards_rejects_overlong_query(client, monkeypatch):
    class FakeSemanticIndex:
        def search_oracle(self, *_args, **_kwargs):
            return []

    monkeypatch.setattr("ot_backend.api._semantic_index.get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "x" * 201})

    assert res.status_code == 422


def test_rejects_disallowed_host_header(client):
    res = client.get("/health", headers={"host": "evil.example"})

    assert res.status_code == 400


def test_admin_semantic_model_routes_require_auth(client):
    res = client.get("/admin/semantic-models")

    assert res.status_code == 401


def test_admin_auth_token_returns_token_for_valid_password(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "swordfish")
    monkeypatch.setenv("ADMIN_JWT_SECRET", "top-secret-with-at-least-thirty-two-bytes")

    res = client.post("/admin/auth/token", json={"password": "swordfish"})

    assert res.status_code == 200
    payload = res.json()
    assert payload["access_token"]
    assert payload["token_type"] == "bearer"
    assert payload["expires_in"] == 28800


def test_admin_auth_token_rejects_invalid_password(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "swordfish")
    monkeypatch.setenv("ADMIN_JWT_SECRET", "top-secret-with-at-least-thirty-two-bytes")

    res = client.post("/admin/auth/token", json={"password": "wrong"})

    assert res.status_code == 401


def test_admin_auth_token_locks_out_ip_after_repeated_failures(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "swordfish")
    monkeypatch.setenv("ADMIN_JWT_SECRET", "top-secret-with-at-least-thirty-two-bytes")
    monkeypatch.setenv("ADMIN_LOGIN_MAX_FAILURES", "3")
    monkeypatch.setenv("ADMIN_LOGIN_LOCKOUT_SECONDS", "120")
    headers = {"X-Forwarded-For": "203.0.113.10"}

    for _ in range(3):
        res = client.post("/admin/auth/token", json={"password": "wrong"}, headers=headers)
        assert res.status_code == 401

    locked_res = client.post("/admin/auth/token", json={"password": "swordfish"}, headers=headers)

    assert locked_res.status_code == 429
    assert 1 <= int(locked_res.headers["Retry-After"]) <= 120
    assert "Too many failed admin login attempts" in locked_res.json()["detail"]


def test_admin_auth_token_success_resets_failure_count_for_ip(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "swordfish")
    monkeypatch.setenv("ADMIN_JWT_SECRET", "top-secret-with-at-least-thirty-two-bytes")
    monkeypatch.setenv("ADMIN_LOGIN_MAX_FAILURES", "3")
    monkeypatch.setenv("ADMIN_LOGIN_LOCKOUT_SECONDS", "120")
    headers = {"X-Forwarded-For": "198.51.100.20"}

    first_failure = client.post("/admin/auth/token", json={"password": "wrong"}, headers=headers)
    success = client.post("/admin/auth/token", json={"password": "swordfish"}, headers=headers)
    second_failure = client.post("/admin/auth/token", json={"password": "wrong"}, headers=headers)

    assert first_failure.status_code == 401
    assert success.status_code == 200
    assert second_failure.status_code == 401


def test_admin_auth_token_lockout_is_scoped_to_source_ip(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "swordfish")
    monkeypatch.setenv("ADMIN_JWT_SECRET", "top-secret-with-at-least-thirty-two-bytes")
    monkeypatch.setenv("ADMIN_LOGIN_MAX_FAILURES", "2")
    monkeypatch.setenv("ADMIN_LOGIN_LOCKOUT_SECONDS", "60")
    blocked_headers = {"X-Forwarded-For": "203.0.113.10"}
    other_headers = {"X-Forwarded-For": "203.0.113.11"}

    client.post("/admin/auth/token", json={"password": "wrong"}, headers=blocked_headers)
    client.post("/admin/auth/token", json={"password": "wrong"}, headers=blocked_headers)

    blocked_res = client.post("/admin/auth/token", json={"password": "swordfish"}, headers=blocked_headers)
    other_res = client.post("/admin/auth/token", json={"password": "swordfish"}, headers=other_headers)

    assert blocked_res.status_code == 429
    assert other_res.status_code == 200


def test_admin_auth_token_prefers_x_real_ip_over_forwarded_for(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "swordfish")
    monkeypatch.setenv("ADMIN_JWT_SECRET", "top-secret-with-at-least-thirty-two-bytes")
    monkeypatch.setenv("ADMIN_LOGIN_MAX_FAILURES", "2")
    monkeypatch.setenv("ADMIN_LOGIN_LOCKOUT_SECONDS", "60")

    spoofed_headers = {
        "X-Real-Ip": "198.51.100.44",
        "X-Forwarded-For": "203.0.113.250, 198.51.100.44",
    }
    victim_headers = {"X-Real-Ip": "203.0.113.250"}

    client.post("/admin/auth/token", json={"password": "wrong"}, headers=spoofed_headers)
    client.post("/admin/auth/token", json={"password": "wrong"}, headers=spoofed_headers)

    spoofed_res = client.post("/admin/auth/token", json={"password": "swordfish"}, headers=spoofed_headers)
    victim_res = client.post("/admin/auth/token", json={"password": "swordfish"}, headers=victim_headers)

    assert spoofed_res.status_code == 429
    assert victim_res.status_code == 200


def test_admin_auth_token_returns_503_when_unconfigured(client, monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("ADMIN_JWT_SECRET", raising=False)

    res = client.post("/admin/auth/token", json={"password": "whatever"})

    assert res.status_code == 503


def test_admin_route_rejects_invalid_bearer_token(client):
    res = client.get("/admin/semantic-models", headers={"Authorization": "Bearer nope"})

    assert res.status_code == 401
