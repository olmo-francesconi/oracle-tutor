"""Tests for the TUI's API health probe.

The public deploy scales to zero. Waking it takes tens of seconds, during which
the edge answers 502/503 — a sleeping service, not a broken one. These pin down
that the probe waits it out, that it does not wait out things that will never
succeed, and that a remote failure stays visible instead of being hidden behind
the localhost fallback.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from types import SimpleNamespace

import pytest


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.text = ""


class _FakeClient:
    """Replays a scripted status code per URL prefix."""

    def __init__(self, script: dict[str, list[int]]) -> None:
        self._script = script
        self.calls: list[str] = []

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get(self, url: str, timeout: float | None = None) -> _FakeResponse:
        self.calls.append(url)
        for prefix, codes in self._script.items():
            if url.startswith(prefix):
                code = codes.pop(0) if len(codes) > 1 else codes[0]
                if code == 0:
                    raise ConnectionError("refused")
                return _FakeResponse(code)
        raise ConnectionError("refused")


def _checks_with(monkeypatch, script: dict[str, list[int]], **env: str):
    client = _FakeClient(script)
    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=lambda **_kw: client))
    monkeypatch.setenv("OT_PUBLIC_URL", "https://example.test")
    monkeypatch.setenv("OT_TUI_API_POLL_INTERVAL", "0")
    monkeypatch.setenv("OT_TUI_API_WAKE_BUDGET", env.get("budget", "5"))
    import ot_backend.tui.checks as checks

    return importlib.reload(checks), client


def test_a_cold_start_is_waited_out(monkeypatch) -> None:
    """502 twice then 200 is a waking service, and must report ok."""
    checks, client = _checks_with(monkeypatch, {"https://example.test": [502, 502, 200]})

    result = asyncio.run(checks.check_api())

    assert result.status == "ok"
    assert "awake after" in result.detail
    assert len(client.calls) == 3


def test_a_service_that_never_wakes_gives_up(monkeypatch) -> None:
    checks, _ = _checks_with(monkeypatch, {"https://example.test": [503]}, budget="0")

    result = asyncio.run(checks.check_api())

    assert result.status == "skipped"
    assert "gave up" in result.detail


def test_a_4xx_is_not_treated_as_a_cold_start(monkeypatch) -> None:
    """A bad URL will never become a good one; polling it just wastes the budget."""
    checks, client = _checks_with(monkeypatch, {"https://example.test": [404]})

    result = asyncio.run(checks.check_api())

    assert result.status == "skipped"
    remote_calls = [c for c in client.calls if c.startswith("https://example.test")]
    assert len(remote_calls) == 1


def test_both_candidate_failures_are_reported(monkeypatch) -> None:
    """Reporting only the last one made a failing remote look unchecked."""
    checks, _ = _checks_with(monkeypatch, {"https://example.test": [404]})

    result = asyncio.run(checks.check_api())

    assert "https://example.test/api/health" in result.detail
    assert "http://localhost:8000/health" in result.detail


def test_localhost_answers_when_no_public_url_is_set(monkeypatch) -> None:
    client = _FakeClient({"http://localhost:8000": [200]})
    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=lambda **_kw: client))
    monkeypatch.delenv("OT_PUBLIC_URL", raising=False)
    import ot_backend.tui.checks as checks

    checks = importlib.reload(checks)
    result = asyncio.run(checks.check_api())

    assert result.status == "ok"
    assert client.calls == ["http://localhost:8000/health"]


@pytest.fixture(autouse=True)
def _restore_checks_module():
    """The tests reload the module with patched env; put it back afterwards."""
    yield
    import ot_backend.tui.checks as checks

    importlib.reload(checks)
