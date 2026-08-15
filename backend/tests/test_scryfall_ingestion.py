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
