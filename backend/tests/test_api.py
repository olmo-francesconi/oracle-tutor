from ot_backend.api.routers.search import _CARD_TYPE_MAP, _FORMAT_MAP, _parse_code_filter
from ot_backend.semantic.index import SimilarityHit


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
        model_id = None

        def similar_to_face(self, *_args, **_kwargs):
            return [SimilarityHit(face_key=("o2", 0), score=0.95, matched_ability="deal damage")]

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
                "matched_ability": "deal damage",
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
        model_id = None

        def search_oracle(self, *_args, **_kwargs):
            return [SimilarityHit(face_key=("o6", 1), score=0.91, matched_ability="deal damage")]

    monkeypatch.setattr("ot_backend.api._semantic_index.get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "tap draw", "limit": 10})
    assert res.status_code == 200
    assert res.json()["items"][0]["face_ix"] == 1
    assert res.json()["items"][0]["image_side"] == "front"
    assert res.json()["items"][0]["name"] == "Ice"


def test_similar_cards_uses_back_image_side_for_double_faced_back_face(client, monkeypatch):
    class FakeSemanticIndex:
        model_id = None

        def search_oracle(self, *_args, **_kwargs):
            return [SimilarityHit(face_key=("o7", 1), score=0.89, matched_ability="deal damage")]

    monkeypatch.setattr("ot_backend.api._semantic_index.get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "werewolf", "limit": 10})
    assert res.status_code == 200
    assert res.json()["items"][0]["face_ix"] == 1
    assert res.json()["items"][0]["image_side"] == "back"
    assert res.json()["items"][0]["name"] == "Moonrage Brute"


def test_similar_cards_sets_has_more_when_more_results_exist(client, monkeypatch):
    class FakeSemanticIndex:
        model_id = None

        def search_oracle(self, *_args, **_kwargs):
            return [
                SimilarityHit(face_key=("o2", 0), score=0.95, matched_ability="deal damage"),
                SimilarityHit(face_key=("o1", 0), score=0.9, matched_ability="draw a card"),
            ]

    monkeypatch.setattr("ot_backend.api._semantic_index.get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get("/similar-cards", params={"q": "shock", "limit": 1, "offset": 0})
    assert res.status_code == 200
    assert len(res.json()["items"]) == 1
    assert res.json()["has_more"] is True


def test_similar_cards_sets_has_more_false_on_last_page(client, monkeypatch):
    class FakeSemanticIndex:
        model_id = None

        def search_oracle(self, *_args, **_kwargs):
            return [
                SimilarityHit(face_key=("o2", 0), score=0.95, matched_ability="deal damage"),
                SimilarityHit(face_key=("o1", 0), score=0.9, matched_ability="draw a card"),
            ]

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


def test_similar_cards_rejects_invalid_match_mode(client):
    res = client.get("/similar-cards", params={"q": "shock", "match_mode": "bogus"})
    assert res.status_code == 422


def test_similar_cards_rejects_invalid_color_feature(client):
    res = client.get("/similar-cards", params={"q": "shock", "color_feature": "colours"})
    assert res.status_code == 422


def test_similar_cards_accepts_valid_match_mode_and_color_feature(client, monkeypatch):
    class FakeSemanticIndex:
        model_id = None

        def search_oracle(self, *_args, **_kwargs):
            return []

    monkeypatch.setattr("ot_backend.api._semantic_index.get_semantic_index", lambda: FakeSemanticIndex())

    res = client.get(
        "/similar-cards",
        params={"q": "shock", "match_mode": "exact", "color_feature": "colors"},
    )
    assert res.status_code == 200


def test_similar_cards_rejects_offset_over_cap(client):
    res = client.get("/similar-cards", params={"q": "shock", "offset": 10_001})
    assert res.status_code == 422


def test_search_rejects_offset_over_cap(client):
    res = client.get("/search", params={"q": "shock", "offset": 10_001})
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
        model_id = None

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


# ---------------------------------------------------------------------------
# Ability tuning params
# ---------------------------------------------------------------------------


class _CapturingSemanticIndex:
    """Records the kwargs the route hands the index, and returns nothing."""

    model_id = None

    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    def similar_to_face(self, *_args, **kwargs):
        self.kwargs = kwargs
        return []

    def search_oracle(self, *_args, **kwargs):
        self.kwargs = kwargs
        return []


def _capture_index(monkeypatch) -> _CapturingSemanticIndex:
    index = _CapturingSemanticIndex()
    monkeypatch.setattr("ot_backend.api._semantic_index.get_semantic_index", lambda: index)
    return index


def test_similar_cards_parses_ability_selection(client, monkeypatch):
    index = _capture_index(monkeypatch)

    res = client.get(
        "/similar-cards",
        params={"oracle_id": "o1", "include_abilities": "2,0,2", "exclude_abilities": "1"},
    )

    assert res.status_code == 200
    # Deduplicated and sorted, so the same selection always hits the same cache key.
    assert index.kwargs["include_abilities"] == [0, 2]
    assert index.kwargs["exclude_abilities"] == [1]


def test_similar_cards_defaults_ability_selection_to_none(client, monkeypatch):
    index = _capture_index(monkeypatch)

    res = client.get("/similar-cards", params={"oracle_id": "o1"})

    assert res.status_code == 200
    assert index.kwargs["include_abilities"] is None
    assert index.kwargs["exclude_abilities"] is None


def test_similar_cards_ignores_empty_ability_selection(client, monkeypatch):
    index = _capture_index(monkeypatch)

    res = client.get("/similar-cards", params={"oracle_id": "o1", "include_abilities": ""})

    assert res.status_code == 200
    assert index.kwargs["include_abilities"] is None


def test_similar_cards_rejects_non_integer_abilities(client, monkeypatch):
    _capture_index(monkeypatch)

    res = client.get("/similar-cards", params={"oracle_id": "o1", "include_abilities": "0,nope"})

    assert res.status_code == 422


def test_similar_cards_rejects_negative_abilities(client, monkeypatch):
    _capture_index(monkeypatch)

    res = client.get("/similar-cards", params={"oracle_id": "o1", "exclude_abilities": "-1"})

    assert res.status_code == 422


def test_similar_cards_rejects_ability_in_both_selections(client, monkeypatch):
    _capture_index(monkeypatch)

    res = client.get(
        "/similar-cards",
        params={"oracle_id": "o1", "include_abilities": "0,1", "exclude_abilities": "1"},
    )

    assert res.status_code == 422


def test_card_detail_exposes_segmented_abilities(client):
    from ot_backend.core.database import SessionLocal
    from ot_backend.core.models import CardFaceAbility

    with SessionLocal() as db:
        db.add_all(
            [
                CardFaceAbility(
                    oracle_id="o1", face_ix=0, ability_ix=0, text="Flying",
                    normalized_text="flying", text_hash="h-flying", is_keyword=True,
                ),
                CardFaceAbility(
                    oracle_id="o1", face_ix=0, ability_ix=1, text="Draw a card.",
                    normalized_text="draw a card.", text_hash="h-draw", is_keyword=False,
                ),
                # Placeholder row for rules-text-free faces: nothing to click.
                CardFaceAbility(
                    oracle_id="o1", face_ix=0, ability_ix=2, text="",
                    normalized_text="<empty>", text_hash="h-empty", is_keyword=False,
                ),
            ]
        )
        db.commit()

    res = client.get("/card/o1")

    assert res.status_code == 200
    assert res.json()["faces"][0]["abilities"] == [
        {"ability_ix": 0, "text": "Flying", "is_keyword": True},
        {"ability_ix": 1, "text": "Draw a card.", "is_keyword": False},
    ]
