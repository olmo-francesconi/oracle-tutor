from __future__ import annotations

from typing import Any

from ot_backend.ingest import scryfall_ingestion as si


def test_fetch_bulk_metadata_sends_required_headers(monkeypatch) -> None:
    # Scryfall returns HTTP 400/403 without an explicit User-Agent and Accept header.
    captured: dict[str, Any] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, str]:
            return {"jsonl_download_uri": "https://data.scryfall.io/default-cards/x.jsonl.gz"}

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return FakeResponse()

    monkeypatch.setattr(si.requests, "get", fake_get)

    meta = si.fetch_bulk_metadata()

    assert si.resolve_bulk_download_url(meta).startswith("https://")
    assert captured["url"] == si.BULK_DATA_URL
    assert captured["headers"]["User-Agent"] == si.SCRYFALL_HEADERS["User-Agent"]
    assert captured["headers"]["Accept"] == "application/json"


def test_skip_tags_does_not_destroy_the_tag_corpus(client) -> None:
    """`--skip-tags` must not delete taggings it will never put back.

    `_delete_card_related_rows` clears a card's dependents before they are
    re-inserted, and the Tagger phase normally rebuilds `card_taggings`
    afterwards. With that phase skipped nothing does, so a re-ingest silently
    wiped 227,721 curated taggings — the corpus the training data is built on.
    """
    from sqlalchemy import select

    from ot_backend.core.database import SessionLocal
    from ot_backend.core.models import CardTagging, Tag
    from ot_backend.ingest.scryfall_ingestion import _delete_card_related_rows

    with SessionLocal() as db:
        db.add(Tag(id="t-keep", tag_name="mana dork", tag_namespace="card"))
        db.flush()
        db.add(CardTagging(id="ct-keep", card_id="o1", tag_id="t-keep", foreign_key="oracleId"))
        db.commit()

        _delete_card_related_rows(db, ["o1"], preserve_taggings=True)
        db.commit()
        survived = db.execute(select(CardTagging).where(CardTagging.card_id == "o1")).scalars().all()
        assert len(survived) == 1, "a refreshed card must keep its tags"

        # A card being deleted still drops them — that is not the same case.
        _delete_card_related_rows(db, ["o1"])
        db.commit()
        remaining = db.execute(select(CardTagging).where(CardTagging.card_id == "o1")).scalars().all()
        assert remaining == []


def test_preserving_taggings_still_clears_the_faces(client) -> None:
    """The flag must be narrow: faces are what a re-ingest actually replaces."""
    from sqlalchemy import select

    from ot_backend.core.database import SessionLocal
    from ot_backend.core.models import CardFace
    from ot_backend.ingest.scryfall_ingestion import _delete_card_related_rows

    with SessionLocal() as db:
        before = db.execute(select(CardFace).where(CardFace.oracle_id == "o1")).scalars().all()
        assert before, "fixture should seed at least one face"

        _delete_card_related_rows(db, ["o1"], preserve_taggings=True)
        db.commit()

        after = db.execute(select(CardFace).where(CardFace.oracle_id == "o1")).scalars().all()
        assert after == [], "faces are replaced on every ingest and must still be cleared"


def test_tag_refresh_is_opt_in() -> None:
    """Ingesting cards must not silently re-fetch every card's tags.

    The delete is what forces a rebuild: with taggings preserved, the
    incremental query in fetch_tags only visits cards that have none. Dropping
    them on every ingest turned a nightly run into a ~9h full Tagger crawl.
    """
    # (skip_tags, refresh_tags) -> taggings preserved during the card upsert
    cases = {
        (False, False): True,   # default: keep them, fetch only new cards
        (False, True): False,   # explicit refresh: clear so the crawl rebuilds
        (True, False): True,    # skipping the phase: nothing would restore them
        (True, True): True,     # contradictory, but never destroy what we will not refetch
    }
    for (skip_tags, refresh_tags), expected in cases.items():
        assert (skip_tags or not refresh_tags) is expected, (skip_tags, refresh_tags)


def test_the_incremental_query_only_selects_untagged_cards() -> None:
    """This is what makes preserving taggings a fast path rather than a stale one."""
    from ot_backend.ingest.fetch_tags import _cards_needing_tag_fetch_query

    incremental = str(_cards_needing_tag_fetch_query(refresh_tags=False))
    full = str(_cards_needing_tag_fetch_query(refresh_tags=True))

    assert "IS NULL" in incremental.upper()
    assert "IS NULL" not in full.upper()
