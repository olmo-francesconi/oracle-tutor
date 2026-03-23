from __future__ import annotations

from ot_backend.embed import main as embed_main


def test_main_skips_training_with_no_train(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr("ot_backend.embed.main._semantic_device", lambda: "cpu")
    monkeypatch.setattr("ot_backend.embed.main.semantic_model_path", lambda: "semantic-model")
    monkeypatch.setattr("ot_backend.embed.main.semantic_model_source", lambda: "semantic-source")
    monkeypatch.setattr(
        "ot_backend.embed.main.train.main",
        lambda: calls.append("train") or 0,
    )
    monkeypatch.setattr(
        "ot_backend.embed.main.train.export_onnx_model",
        lambda model_source, output_path: calls.append(f"export:{model_source}:{output_path}"),
    )
    monkeypatch.setattr(
        "ot_backend.embed.main.compute.main",
        lambda: calls.append("compute") or 0,
    )

    exit_code = embed_main.main(["--no-train"])

    assert exit_code == 0
    assert calls == ["export:semantic-source:semantic-model", "compute"]


def test_main_runs_training_then_compute_by_default(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr("ot_backend.embed.main._semantic_device", lambda: "cpu")
    monkeypatch.setattr("ot_backend.embed.main.semantic_model_path", lambda: "semantic-model")
    monkeypatch.setattr("ot_backend.embed.main.semantic_model_source", lambda: "semantic-source")
    monkeypatch.setattr(
        "ot_backend.embed.main.train.main",
        lambda: calls.append("train") or 0,
    )
    monkeypatch.setattr(
        "ot_backend.embed.main.train.export_onnx_model",
        lambda model_source, output_path: calls.append(f"export:{model_source}:{output_path}"),
    )
    monkeypatch.setattr(
        "ot_backend.embed.main.compute.main",
        lambda: calls.append("compute") or 0,
    )

    exit_code = embed_main.main([])

    assert exit_code == 0
    assert calls == ["train", "export:semantic-source:semantic-model", "compute"]
