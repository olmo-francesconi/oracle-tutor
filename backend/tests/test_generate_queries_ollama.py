from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


def _load_script_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "generate_queries_ollama.py"
    spec = importlib.util.spec_from_file_location("test_generate_queries_ollama_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_dataset(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "face_texts": [
                    {
                        "oracle_id": "oracle-1",
                        "face_ix": 0,
                        "text": "this card deals three damage to any target.",
                    }
                ],
                "direct_text_pairs": [],
            }
        ),
        encoding="utf-8",
    )


def test_main_retries_faces_with_empty_checkpoint_queries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script_module()
    dataset_path = tmp_path / "training-dataset.json"
    checkpoint_path = tmp_path / "llm-queries.jsonl"
    _write_dataset(dataset_path)
    checkpoint_path.write_text(
        json.dumps({"oracle_id": "oracle-1", "face_ix": 0, "queries": []}) + "\n",
        encoding="utf-8",
    )

    ollama_calls: list[str] = []

    monkeypatch.setattr(module, "generate_template_queries", lambda text: [])
    monkeypatch.setattr(
        module,
        "_call_ollama",
        lambda oracle_text, model, base_url: ollama_calls.append(oracle_text) or "burn spell\ncheap removal\ninstant damage",
    )
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: object())

    exit_code = module.main(
        [
            "--dataset",
            str(dataset_path),
            "--checkpoint",
            str(checkpoint_path),
            "--ollama-url",
            "http://localhost:11434",
        ]
    )

    assert exit_code == 0
    assert ollama_calls == ["this card deals three damage to any target."]

    rows = [json.loads(line) for line in checkpoint_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows[-1]["queries"] == ["burn spell", "cheap removal", "instant damage"]


def test_main_does_not_checkpoint_empty_parsed_queries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script_module()
    dataset_path = tmp_path / "training-dataset.json"
    checkpoint_path = tmp_path / "llm-queries.jsonl"
    _write_dataset(dataset_path)

    monkeypatch.setattr(module, "generate_template_queries", lambda text: [])
    monkeypatch.setattr(module, "_call_ollama", lambda oracle_text, model, base_url: "bad\nx")
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: object())

    exit_code = module.main(
        [
            "--dataset",
            str(dataset_path),
            "--checkpoint",
            str(checkpoint_path),
            "--ollama-url",
            "http://localhost:11434",
        ]
    )

    assert exit_code == 0
    assert checkpoint_path.read_text(encoding="utf-8") == ""


def test_merge_is_idempotent_and_preserves_existing_pairs(tmp_path: Path) -> None:
    module = _load_script_module()
    dataset_path = tmp_path / "training-dataset.json"
    first_output = tmp_path / "training-dataset-llm.json"
    second_output = tmp_path / "training-dataset-llm-2.json"
    dataset_path.write_text(
        json.dumps(
            {
                "face_texts": [
                    {
                        "oracle_id": "oracle-1",
                        "face_ix": 0,
                        "text": "this card deals three damage to any target.",
                    }
                ],
                "direct_text_pairs": [["burn spell", "this card deals three damage to any target."]],
                "llm_query_examples": 1,
            }
        ),
        encoding="utf-8",
    )

    checkpoint = {
        "oracle-1:0": [
            "burn spell",
            "burn spell",
            "instant damage",
        ]
    }

    module._merge(dataset_path, checkpoint, first_output)
    module._merge(first_output, checkpoint, second_output)

    first_payload = json.loads(first_output.read_text(encoding="utf-8"))
    second_payload = json.loads(second_output.read_text(encoding="utf-8"))

    expected_pairs = [
        ["burn spell", "this card deals three damage to any target."],
        ["instant damage", "this card deals three damage to any target."],
    ]

    assert first_payload["direct_text_pairs"] == expected_pairs
    assert first_payload["llm_query_examples"] == 2
    assert second_payload["direct_text_pairs"] == expected_pairs
    assert second_payload["llm_query_examples"] == 2
