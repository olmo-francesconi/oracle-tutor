import json

import pytest

from app import log as log_module
from app.log import log


@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr(log_module, "TTY", True)


@pytest.fixture
def piped(monkeypatch):
    monkeypatch.setattr(log_module, "TTY", False)


def test_piped_output_is_one_json_object_per_line(piped, capsys):
    log("search", mode="text", q="draw a card", exclude=[0, 2], ms=18)
    log("snapshot poll failed", level="warning")
    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line) for line in lines] == [
        {"level": "info", "msg": "search", "mode": "text", "q": "draw a card", "exclude": [0, 2], "ms": 18},
        {"level": "warning", "msg": "snapshot poll failed"},
    ]


def test_exception_stays_on_one_json_line(piped, capsys):
    try:
        raise ValueError("boom")
    except ValueError as exc:
        log("request failed", level="error", exc=exc, path="/api/similar-cards")
    (line,) = capsys.readouterr().out.splitlines()
    record = json.loads(line)
    assert record["error"] == "ValueError: boom"
    assert record["path"] == "/api/similar-cards"
    assert "Traceback" in record["traceback"] and "boom" in record["traceback"]


def test_terminal_output_quotes_only_values_that_need_it(tty, capsys):
    log("search", mode="text", q="draw a card", empty="", results=3)
    line = capsys.readouterr().out.rstrip("\n")
    assert line.endswith('info    search mode=text q="draw a card" empty="" results=3')


def test_terminal_output_prints_the_traceback_below_the_line(tty, capsys):
    try:
        raise ValueError("boom")
    except ValueError as exc:
        log("snapshot poll failed", level="warning", exc=exc)
    first, *rest = capsys.readouterr().out.splitlines()
    assert first.endswith('warning snapshot poll failed error="ValueError: boom"')
    assert rest[0] == "Traceback (most recent call last):" and rest[-1] == "ValueError: boom"
