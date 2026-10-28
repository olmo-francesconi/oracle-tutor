import subprocess
import sys

import pytest

from train import pipeline


def _run(monkeypatch, ran: list[str], fail_at: str | None = None) -> None:
    def fake_run(cmd, check):
        ran.append(cmd[2])
        return subprocess.CompletedProcess(cmd, 1 if cmd[2] == fail_at else 0)

    monkeypatch.setattr(sys, "argv", ["pipeline", "m-1", "--epochs", "1"])
    monkeypatch.setattr(pipeline.snapshot, "enabled", lambda: True)
    monkeypatch.setattr(pipeline.snapshot, "has_model", lambda _: False)
    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    pipeline.main()


def test_runs_every_step_in_order(monkeypatch):
    ran = []
    _run(monkeypatch, ran)
    assert ran == ["train.tags", "train.dataset", "train.train", "train.eval", "app.build"]


def test_failed_step_stops_before_promotion(monkeypatch):
    ran = []
    with pytest.raises(SystemExit, match="train.train failed; m-1 not promoted"):
        _run(monkeypatch, ran, fail_at="train.train")
    assert ran == ["train.tags", "train.dataset", "train.train"]
