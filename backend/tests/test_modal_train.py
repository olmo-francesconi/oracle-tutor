from __future__ import annotations

import json
from pathlib import Path

import pytest

from ot_backend.semantic import modal_train


def test_build_dataset_state_adds_llm_query_pairs(monkeypatch) -> None:
    monkeypatch.setattr("ot_backend.semantic.modal_train.semantic_llm_model_name", lambda: "test-llm")
    monkeypatch.setattr(
        "ot_backend.semantic.modal_train._generate_llm_query_pairs",
        lambda _rows, llm_config=None: [("burn spell", "this card deals two damage to any target.")],
    )

    payload = {
        "version": 1,
        "features": {
            "tag_pairs": False,
            "tag_descriptions": False,
            "template_queries": False,
            "llm_queries": True,
        },
        "options": {},
        "faces": [
            {
                "oracle_id": "o1",
                "face_ix": 0,
                "name": "Shock",
                "type_line": "Instant",
                "oracle_text": "Shock deals 2 damage to any target.",
                "text": "this card deals two damage to any target.",
            }
        ],
        "metadata": {"semantic_data_version": 7},
    }

    state, metadata = modal_train._build_dataset_state(payload, augmentation_mode="llm_queries")

    assert state.simcse_examples == 1
    assert state.llm_query_examples == 1
    assert state.direct_text_pairs == [("burn spell", "this card deals two damage to any target.")]
    assert metadata["augmentation"]["llm_model"] == "test-llm"


def test_parse_llm_queries_matches_ollama_rules() -> None:
    assert modal_train._parse_llm_queries("<think>hidden</think>\n1. burn spell\n2. direct damage", max_queries=4) == [
        "burn spell",
        "direct damage",
    ]
    assert modal_train._parse_llm_queries("shock\nred instant removal", max_queries=4) == ["red instant removal"]


def test_build_llm_prompt_uses_oracle_text_only() -> None:
    prompt = modal_train._build_llm_prompt(
        {
            "name": "Shock",
            "type_line": "Instant",
            "oracle_text": "This card deals three damage to any target.",
            "text": "this card deals three damage to any target.",
        },
        max_queries=3,
    )

    assert "Card name:" not in prompt
    assert "Type line:" not in prompt
    assert "This card deals three damage to any target." in prompt


def test_select_llm_gap_faces_uses_template_coverage(monkeypatch) -> None:
    monkeypatch.setattr(
        "ot_backend.semantic.modal_train.generate_template_queries",
        lambda text: ["draw a card", "card draw"] if text == "Draw a card." else [],
    )
    selected = modal_train._select_llm_gap_faces(
        [
            {"oracle_text": "Draw a card.", "text": "Draw a card."},
            {
                "oracle_text": "When this creature enters the battlefield, creatures you control get +1/+1 until end of turn.",
                "text": "When this creature enters the battlefield, creatures you control get +1/+1 until end of turn.",
            },
        ],
        min_template_coverage=2,
        max_faces=10,
    )

    assert selected == [
        {
            "oracle_text": "When this creature enters the battlefield, creatures you control get +1/+1 until end of turn.",
            "text": "When this creature enters the battlefield, creatures you control get +1/+1 until end of turn.",
        }
    ]


def test_select_llm_gap_faces_skips_blank_oracle_rows(monkeypatch) -> None:
    monkeypatch.setattr("ot_backend.semantic.modal_train.generate_template_queries", lambda _text: [])

    selected = modal_train._select_llm_gap_faces(
        [
            {"oracle_text": "", "text": "emptyoracle"},
            {"oracle_text": "Draw a card.", "text": "Draw a card."},
        ],
        min_template_coverage=2,
        max_faces=10,
    )

    assert selected == [{"oracle_text": "Draw a card.", "text": "Draw a card."}]


def _tag_payload(version: int, anchors: object) -> dict[str, object]:
    """Minimal payload exercising only the tag_descriptions path."""
    return {
        "version": version,
        "features": {
            "tag_pairs": False,
            "tag_descriptions": True,
            "template_queries": False,
            "llm_queries": False,
        },
        "options": {"max_tag_desc_pairs_per_tag": 10},
        "faces": [
            {
                "oracle_id": "o1",
                "face_ix": 0,
                "name": "Llanowar Elves",
                "type_line": "Creature — Elf Druid",
                "oracle_text": "{T}: Add {G}.",
                "text": "tap this card: Add one green mana.",
            }
        ],
        "tag_to_desc": {"mana dork": anchors},
        "tag_to_desc_faces": {"mana dork": [["o1", 0]]},
        "metadata": {"semantic_data_version": 7},
    }


def test_v2_payload_teaches_both_anchors() -> None:
    """The bare name is the string players type; it must reach training."""
    payload = _tag_payload(2, ["mana dork", "mana dork. Low-cost creatures which generate mana"])

    state, _ = modal_train._build_dataset_state(payload, augmentation_mode="tag_descriptions")

    anchors = {anchor for anchor, _text in state.direct_text_pairs}
    assert "mana dork" in anchors
    assert "mana dork. Low-cost creatures which generate mana" in anchors


def test_v1_payload_with_a_single_string_anchor_still_builds() -> None:
    """A payload built before the anchor list must not break the worker."""
    payload = _tag_payload(1, "mana dork. Low-cost creatures which generate mana")

    state, _ = modal_train._build_dataset_state(payload, augmentation_mode="tag_descriptions")

    assert state.direct_text_pairs == [
        ("mana dork. Low-cost creatures which generate mana", "tap this card: Add one green mana.")
    ]


def test_an_unknown_payload_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported training build payload version"):
        modal_train._build_dataset_state(_tag_payload(99, ["x"]), augmentation_mode="tag_descriptions")


def test_persist_bundle_writes_the_zip_and_a_sidecar(tmp_path, monkeypatch) -> None:
    """The volume copy is what survives a client that dies during .remote()."""
    committed: list[bool] = []
    monkeypatch.setattr(modal_train, "_BUNDLE_STORE_PATH", str(tmp_path / "bundles"))
    monkeypatch.setattr(
        modal_train, "bundle_store", type("V", (), {"commit": lambda self: committed.append(True)})()
    )

    written = modal_train._persist_bundle(
        b"PK\x03\x04 bundle", base_model="Qwen/Qwen2.5-14B-Instruct-AWQ", augmentation_mode="tag_pairs"
    )

    path = Path(written)
    assert path.read_bytes() == b"PK\x03\x04 bundle"
    # "/" in the model id must not create nested directories.
    assert "Qwen_Qwen2.5-14B-Instruct-AWQ" in path.name
    sidecar = json.loads(path.with_suffix(".json").read_text())
    assert sidecar["base_model"] == "Qwen/Qwen2.5-14B-Instruct-AWQ"
    assert sidecar["size_bytes"] == len(b"PK\x03\x04 bundle")
    assert committed == [True]


def test_persist_bundle_failure_does_not_sink_a_good_run(monkeypatch) -> None:
    """A backup that raises would throw away the training it was protecting."""
    monkeypatch.setattr(modal_train, "_BUNDLE_STORE_PATH", "/proc/nonexistent/bundles")

    assert modal_train._persist_bundle(b"x", base_model="m", augmentation_mode="a") == ""
