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


def test_suggest_names(client):
    res = client.get("/suggest-names", params={"q": "sho", "limit": 10})
    assert res.status_code == 200
    names = [x["name"] for x in res.json()]
    assert "Shock" in names


def test_search_oracle(client):
    res = client.get("/search-oracle", params={"q": "deals damage any target", "limit": 10, "offset": 0})
    assert res.status_code == 200
    ids = [x["id"] for x in res.json()]
    assert "c1" in ids
    assert "c2" in ids
    assert "c4" in ids
    # c3 matches "target" now that we have c5 (which doesn't have "target"), so "target" is no longer IDF=0.
    # But it should be ranked lower than c1/c2/c4 which match multiple terms.
    assert ids.index("c1") < ids.index("c3")
    assert ids.index("c2") < ids.index("c3")



def test_search_oracle_long_text_not_penalized(client):
    res = client.get("/search-oracle", params={"q": "deals damage any target", "limit": 10, "offset": 0})
    assert res.status_code == 200
    rows = res.json()
    sim_by_id = {x["id"]: x["similarity"] for x in rows}
    assert "c2" in sim_by_id
    assert "c4" in sim_by_id
    # Same matching clause, extra unrelated oracle text should not reduce score.
    assert abs(sim_by_id["c2"] - sim_by_id["c4"]) < 1e-6


def test_search_oracle_digits_affect_ranking(client):
    res = client.get("/search-oracle", params={"q": "deals 3 damage any target", "limit": 10, "offset": 0})
    assert res.status_code == 200
    rows = res.json()
    sim_by_id = {x["id"]: x["similarity"] for x in rows}
    assert "c1" in sim_by_id
    assert "c2" in sim_by_id
    # "3" should match Lightning Bolt but not Shock (which has "2").
    assert sim_by_id["c1"] > sim_by_id["c2"]


def test_similar_cards(client):
    res = client.get("/similar-cards/c1", params={"limit": 10, "offset": 0})
    assert res.status_code == 200
    ids = [x["id"] for x in res.json()]
    assert "c1" not in ids
    assert "c2" in ids


def test_data_endpoints_return_503_while_schema_migrating(client, monkeypatch):
    monkeypatch.setattr("oracle_tutor_api.api.main._schema_ready", False)
    monkeypatch.setattr("oracle_tutor_api.api.main.wait_for_migration_ready", lambda **_: False)

    res = client.get("/search", params={"q": "shock"})
    assert res.status_code == 503


def test_internal_rebuild_rejects_missing_token(client, monkeypatch):
    monkeypatch.setattr("oracle_tutor_api.api.main.WORKER_TRIGGER_TOKEN", "secret-token")
    monkeypatch.setattr("oracle_tutor_api.api.main.WORKER_TRIGGER_ALLOWLIST", ("testclient",))
    monkeypatch.setattr("oracle_tutor_api.api.main._schema_ready", True)

    res = client.post("/internal/rebuild-tfidf")
    assert res.status_code == 401


def test_internal_rebuild_rejects_non_allowlisted_source(client, monkeypatch):
    monkeypatch.setattr("oracle_tutor_api.api.main.WORKER_TRIGGER_TOKEN", "secret-token")
    monkeypatch.setattr("oracle_tutor_api.api.main.WORKER_TRIGGER_ALLOWLIST", ("127.0.0.1",))
    monkeypatch.setattr("oracle_tutor_api.api.main._schema_ready", True)

    res = client.post("/internal/rebuild-tfidf", headers={"X-Worker-Token": "secret-token"})
    assert res.status_code == 403


def test_internal_rebuild_accepts_valid_worker_auth(client, monkeypatch):
    monkeypatch.setattr("oracle_tutor_api.api.main.WORKER_TRIGGER_TOKEN", "secret-token")
    monkeypatch.setattr("oracle_tutor_api.api.main.WORKER_TRIGGER_ALLOWLIST", ("testclient",))
    monkeypatch.setattr("oracle_tutor_api.api.main._schema_ready", True)
    monkeypatch.setattr("oracle_tutor_api.api.main._rebuild_tfidf_index", lambda **_: "v123")

    res = client.post("/internal/rebuild-tfidf", headers={"X-Worker-Token": "secret-token"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["rebuilt"] is True
    assert data["version"] == "v123"


def test_tfidf_endpoints_return_503_while_rebuild_in_progress(client, monkeypatch):
    monkeypatch.setattr("oracle_tutor_api.api.main._schema_ready", True)
    monkeypatch.setattr("oracle_tutor_api.api.main._tfidf_rebuild_in_progress", True)

    res = client.get("/search-oracle", params={"q": "damage", "limit": 5})
    assert res.status_code == 503


def test_internal_rebuild_returns_409_when_rebuild_already_in_progress(client, monkeypatch):
    monkeypatch.setattr("oracle_tutor_api.api.main.WORKER_TRIGGER_TOKEN", "secret-token")
    monkeypatch.setattr("oracle_tutor_api.api.main.WORKER_TRIGGER_ALLOWLIST", ("testclient",))
    monkeypatch.setattr("oracle_tutor_api.api.main._schema_ready", True)
    monkeypatch.setattr("oracle_tutor_api.api.main._tfidf_rebuild_in_progress", True)

    res = client.post("/internal/rebuild-tfidf", headers={"X-Worker-Token": "secret-token"})
    assert res.status_code == 409


def test_internal_rebuild_clears_rebuild_state_after_success(client, monkeypatch):
    import oracle_tutor_api.api.main as api_main

    monkeypatch.setattr("oracle_tutor_api.api.main.WORKER_TRIGGER_TOKEN", "secret-token")
    monkeypatch.setattr("oracle_tutor_api.api.main.WORKER_TRIGGER_ALLOWLIST", ("testclient",))
    monkeypatch.setattr("oracle_tutor_api.api.main._schema_ready", True)
    monkeypatch.setattr("oracle_tutor_api.api.main._tfidf_rebuild_in_progress", False)

    res = client.post("/internal/rebuild-tfidf", headers={"X-Worker-Token": "secret-token"})
    assert res.status_code == 200
    assert api_main._tfidf_rebuild_in_progress is False

