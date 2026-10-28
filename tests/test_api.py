import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def client(index, tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-abc.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text(
        '<html><head>\n<title>Oracle Tutor</title>\n<meta\n  name="description"\n  content="home" />\n'
        '<meta property="og:title" content="home" />\n<meta name="robots" content="index,follow" />\n</head>'
        '<body><div id="root"></div></body></html>'
    )
    monkeypatch.setattr(main, "STATIC_DIR", tmp_path)
    main.app.state.index = index
    return TestClient(main.app)  # no `with`: the lifespan (real model + data) is skipped


def test_ready(client):
    assert client.get("/api/ready").json() == {"ready": True, "model": "fake", "data": "2026-08-18", "snapshot": None}


def test_card_strips_internal_keys(client):
    body = client.get("/api/card/bird").json()
    assert not [k for k in body if k.startswith("_")]
    assert not [k for f in body["faces"] for k in f if k.startswith("_")]
    assert [a["text"] for a in body["faces"][0]["abilities"]] == ["Flying", "When this creature enters, draw a card."]
    assert client.get("/api/card/nope").json() == {"detail": "Card not found"}


def test_search_contract(client):
    [hit] = client.get("/api/search", params={"q": "trample"}).json()
    assert hit == {"name": "Trample Knight", "card_name": "Wing Squire // Trample Knight", "similarity": 1.0,
                   "rank": None, "oracle_id": "dfc", "scryfall_id": "sdfc", "face_ix": 1, "image_side": "back"}
    assert client.get("/api/search", params={"q": "x", "offset": 501}).status_code == 422


def test_similar_cards_contract(client):
    body = client.get("/api/similar-cards", params={"oracle_id": "bird", "limit": 2}).json()
    assert body["has_more"] is True and body["query_abilities"] is None
    assert set(body["items"][0]) == {
        "oracle_id", "scryfall_id", "face_ix", "image_side", "name", "card_name", "similarity", "matched_ability",
        "rank", "type_line", "mana_cost", "oracle_text", "power", "toughness", "colors", "layout", "rarity",
        "legalities", "border_color", "set_code",
    }
    last = client.get("/api/similar-cards", params={"oracle_id": "bird", "limit": 100}).json()
    assert last["has_more"] is False
    paged = client.get("/api/similar-cards", params={"oracle_id": "bird", "limit": 1, "offset": 1}).json()
    assert paged["items"][0]["oracle_id"] == body["items"][1]["oracle_id"]


def test_similar_cards_text_mode_echoes_segmentation(client):
    body = client.get("/api/similar-cards", params={"q": "flying // draw a card", "card_type": "c"}).json()
    assert body["query_abilities"] == ["flying", "draw a card"]
    assert body["items"][0]["oracle_id"] == "bird"


@pytest.mark.parametrize("params,detail", [
    ({}, "Provide either oracle_id or q"),
    ({"q": "a // b // c // d // e // f // g"}, "Query has 7 abilities"),
    ({"q": "x", "format": "mm"}, "Duplicate format codes"),
    ({"q": "x", "card_type": "z"}, "Invalid card type codes: z"),
    ({"q": "x", "rarity": "q"}, "Invalid rarity characters"),
    ({"oracle_id": "bird", "include_abilities": "a"}, "expected comma-separated integers"),
    ({"oracle_id": "bird", "exclude_abilities": "-1"}, "must be non-negative"),
])
def test_similar_cards_validation(client, params, detail):
    r = client.get("/api/similar-cards", params=params)
    assert r.status_code == 422 and detail in r.json()["detail"]


@pytest.mark.parametrize("params", [{"offset": 501}, {"limit": 101}, {"match_mode": "most"}, {"q": "x" * 201}])
def test_similar_cards_bounds(client, params):
    assert client.get("/api/similar-cards", params={"q": "x", **params}).status_code == 422


def test_six_query_abilities_are_allowed(client):
    assert client.get("/api/similar-cards", params={"q": "a // b // c // d // e // f"}).status_code == 200


def test_include_and_exclude_overlap_is_not_an_error(client):
    r = client.get("/api/similar-cards", params={"oracle_id": "bird", "include_abilities": "0,1",
                                                 "exclude_abilities": "0"})
    assert r.status_code == 200
    assert "drake" not in [i["oracle_id"] for i in r.json()["items"]]


def test_spa_serves_files_and_falls_back_to_index(client):
    asset = client.get("/assets/app-abc.js")
    assert asset.headers["cache-control"] == "public, max-age=2592000, immutable"
    home = client.get("/")
    assert home.status_code == 200 and "<title>Oracle Tutor</title>" in home.text
    assert '<div id="root"><main><h1>Oracle Tutor</h1>' in home.text and 'content="index,follow"' in home.text
    assert home.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in home.headers["content-security-policy"]
    assert client.get("/api/nope").status_code == 404
    assert client.get("/../../etc/passwd").status_code == 404


@pytest.mark.parametrize("url", ["/some/route", "/?card=nope"])
def test_unknown_pages_are_404_noindex_but_still_render_the_app(client, url):
    page = client.get(url)
    assert page.status_code == 404 and "<title>Oracle Tutor</title>" in page.text
    assert 'content="noindex,follow"' in page.text and 'content="index,follow"' not in page.text


def test_card_page_gets_its_own_meta(client):
    page = client.get("/", params={"card": "bird"}).text
    assert page.count("<title>") == 1 and "<title>Night Bird | Oracle Tutor</title>" in page
    assert 'content="home"' not in page and 'name="robots"' in page
    assert 'href="http://testserver/?card=bird"' in page and '"@type": "Game"' in page
    assert '<div id="root"><main><h1>Night Bird</h1><section><p>Creature' in page and "<p>Flying</p>" in page
    page = client.get("/", params={"q": '<script>"x"'})
    assert page.status_code == 200 and 'content="noindex,follow"' in page.text
    assert "<title>&quot;&lt;script&gt;&quot;x&quot;&quot; | Oracle Tutor</title>" in page.text
    assert "<script>" not in page.text.split("<body>")[1]


def test_double_faced_card_body_names_each_face(client):
    page = client.get("/", params={"card": "dfc"}).text
    assert "<h1>Wing Squire // Trample Knight</h1>" in page and "<h2>Trample Knight</h2>" in page


def test_sitemap(client):
    body = client.get("/sitemap.xml").text
    assert "<loc>http://testserver/?card=bird</loc>" in body and body.count("<url>") == 9
    assert "<loc>http://testserver/</loc><lastmod>2026-08-18</lastmod>" in body and body.count("<lastmod>") == 1
