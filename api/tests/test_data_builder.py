import requests

from oracle_tutor_api.worker import data_builder
from oracle_tutor_api.worker.data_builder import should_skip_card, trigger_tfidf_rebuild_best_effort


def test_should_skip_card_skips_a_prefix_name() -> None:
    card = {
        "name": "A-Prosperous Thief",
        "layout": "normal",
        "type_line": "Creature — Human Ninja",
        "oracle_text": "Whenever one or more Ninjas you control deal combat damage to a player, create a Treasure token.",
    }
    assert should_skip_card(card) is True


def test_should_skip_card_skips_a_prefix_face_name() -> None:
    card = {
        "name": "Prosperous Thief",
        "layout": "transform",
        "card_faces": [
            {
                "name": "A-Prosperous Thief",
                "type_line": "Creature — Human Ninja",
                "oracle_text": "Some text",
            }
        ],
    }
    assert should_skip_card(card) is True


def test_should_skip_card_skips_when_games_excludes_paper() -> None:
    card = {
        "name": "Digital Only Card",
        "layout": "normal",
        "type_line": "Instant",
        "games": ["arena"],
    }
    assert should_skip_card(card) is True


def test_should_skip_card_does_not_skip_when_games_includes_paper() -> None:
    card = {
        "name": "Paper Card",
        "layout": "normal",
        "type_line": "Instant",
        "games": ["paper", "arena"],
    }
    assert should_skip_card(card) is False


def test_should_skip_card_skips_arena_only_heuristic() -> None:
    card = {
        "name": "Arena Only Card",
        "layout": "normal",
        "type_line": "Creature — Goblin",
        "arena_id": 12345,
        "multiverse_ids": [],
        # no mtgo_id/tcgplayer_id/cardmarket_id
    }
    assert should_skip_card(card) is True


def test_should_skip_card_does_not_skip_paper_card_that_has_arena_id() -> None:
    # Many normal paper cards also have arena_id; we should not exclude them.
    card = {
        "name": "Ravnica at War",
        "layout": "normal",
        "type_line": "Sorcery",
        "arena_id": 69479,
        "multiverse_ids": [460955],
        "mtgo_id": 71662,
        "tcgplayer_id": 187123,
        "cardmarket_id": 371808,
    }
    assert should_skip_card(card) is False


def test_should_not_skip_digital_representative_if_paper_legal() -> None:
    # This simulates the "Black Lotus" case where the oracle-cards representative
    # is the Vintage Masters (online-only) version, but the card is legal/restricted in Vintage.
    card = {
        "name": "Black Lotus",
        "layout": "normal",
        "type_line": "Artifact",
        "games": ["mtgo"],
        "legalities": {
            "standard": "not_legal",
            "pioneer": "not_legal",
            "modern": "not_legal",
            "legacy": "banned",
            "vintage": "restricted",
            "commander": "banned",
            "pauper": "not_legal",
        },
    }
    assert should_skip_card(card) is False


def test_trigger_tfidf_rebuild_posts_to_api(monkeypatch) -> None:
    calls: list[dict] = []

    class DummyResponse:
        status_code = 200
        text = "ok"

    def fake_post(url, headers=None, timeout=None):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return DummyResponse()

    monkeypatch.setattr(data_builder, "API_BASE_URL", "http://api-internal:8000")
    monkeypatch.setattr(data_builder, "WORKER_REBUILD_PATH", "/internal/rebuild-tfidf")
    monkeypatch.setattr(data_builder, "WORKER_TRIGGER_TOKEN", "secret-token")
    monkeypatch.setattr(data_builder, "WORKER_REBUILD_TIMEOUT_SECONDS", 1.5)
    monkeypatch.setattr(requests, "post", fake_post)

    trigger_tfidf_rebuild_best_effort(async_call=False)

    assert len(calls) == 1
    assert calls[0]["url"] == "http://api-internal:8000/internal/rebuild-tfidf"
    assert calls[0]["headers"]["X-Worker-Token"] == "secret-token"
    assert calls[0]["headers"]["X-Worker-Source"] == "worker"
    assert calls[0]["timeout"] == 1.5


def test_trigger_tfidf_rebuild_failure_is_best_effort(monkeypatch) -> None:
    def fake_post(url, headers=None, timeout=None):
        raise requests.RequestException("network error")

    monkeypatch.setattr(data_builder, "API_BASE_URL", "http://api-internal:8000")
    monkeypatch.setattr(data_builder, "WORKER_REBUILD_PATH", "/internal/rebuild-tfidf")
    monkeypatch.setattr(data_builder, "WORKER_TRIGGER_TOKEN", "secret-token")
    monkeypatch.setattr(requests, "post", fake_post)

    # Should not raise.
    trigger_tfidf_rebuild_best_effort(async_call=False)
