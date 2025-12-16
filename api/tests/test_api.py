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
    assert "c3" not in ids


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


