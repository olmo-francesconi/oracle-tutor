import sys

import pytest

from train import pipeline


class FakeProc:
    def __init__(self, step: str, fail: bool):
        self.stdout = iter([f"{step} working\n", "\n"])
        self.returncode = 1 if fail else 0

    def wait(self) -> int:
        return self.returncode


def _run(monkeypatch, tmp_path, ran: list[str], uploads: dict, fail_at: str | None = None) -> None:
    def fake_popen(cmd, **_):
        ran.append(cmd[2])
        return FakeProc(cmd[2], cmd[2] == fail_at)

    checks = iter([False, fail_at is None])  # before: not in the bucket yet; after: uploaded unless training failed
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BUCKET", "b")
    monkeypatch.setattr(sys, "argv", ["pipeline", "m-1", "--epochs", "1"])
    monkeypatch.setattr(pipeline.snapshot, "has_model", lambda _: next(checks))
    monkeypatch.setattr(pipeline.snapshot, "read_pointer", lambda: {"snapshot": "s", "model": "old"})
    monkeypatch.setattr(pipeline.snapshot, "put", lambda key, body, _: uploads.update({key: body}))
    monkeypatch.setattr(pipeline.subprocess, "Popen", fake_popen)
    pipeline.main()


def test_runs_every_step_in_order_and_uploads_the_log(monkeypatch, tmp_path):
    ran, uploads = [], {}
    _run(monkeypatch, tmp_path, ran, uploads)
    assert ran == ["train.tags", "train.dataset", "train.train", "train.eval", "app.build"]
    log = (tmp_path / "train/runs/m-1/pipeline.log").read_text()
    assert "train.train working" in log and "[5/5] promote done" in log and "m-1 promoted" in log
    assert uploads["models/m-1/pipeline.log"].decode() == log


def test_failed_step_stops_before_promotion(monkeypatch, tmp_path):
    ran, uploads = [], {}
    with pytest.raises(SystemExit, match="train failed; m-1 not promoted"):
        _run(monkeypatch, tmp_path, ran, uploads, fail_at="train.train")
    assert ran == ["train.tags", "train.dataset", "train.train"]
    assert "[3/5] train FAILED" in (tmp_path / "train/runs/m-1/pipeline.log").read_text()
    assert not uploads
