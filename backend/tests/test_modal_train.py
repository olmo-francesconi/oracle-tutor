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
        "version": 3,
        "features": {
            "tag_pairs": False,
            "tag_descriptions": False,
            "template_queries": False,
            "llm_queries": True,
        },
        "options": {},
        "abilities": [
            {
                "oracle_id": "o1",
                "face_ix": 0,
                "ability_ix": 0,
                "raw": "Shock deals 2 damage to any target.",
                "text": "this card deals two damage to any target.",
            }
        ],
        "card_names": [{"oracle_id": "o1", "face_ix": 0, "name": "Shock"}],
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
        "abilities": [
            {
                "oracle_id": "o1",
                "face_ix": 0,
                "ability_ix": 0,
                "raw": "{T}: Add {G}.",
                "text": "tap this card: Add one green mana.",
            }
        ],
        "card_names": [{"oracle_id": "o1", "face_ix": 0, "name": "Llanowar Elves"}],
        "tag_to_desc": {"mana dork": anchors},
        "tag_to_ability_ids": {"mana dork": [["o1", 0, 0]]},
        "metadata": {"semantic_data_version": 7},
    }


def test_a_tag_teaches_both_anchors() -> None:
    """The bare name is the string players type; it must reach training."""
    payload = _tag_payload(3, ["mana dork", "mana dork. Low-cost creatures which generate mana"])

    state, _ = modal_train._build_dataset_state(payload, augmentation_mode="tag_descriptions")

    anchors = {anchor for anchor, _text in state.direct_text_pairs}
    assert "mana dork" in anchors
    assert "mana dork. Low-cost creatures which generate mana" in anchors


def test_a_single_string_anchor_still_builds() -> None:
    """Anchors are a list, but a bare string must not break the worker."""
    payload = _tag_payload(3, "mana dork. Low-cost creatures which generate mana")

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
    monkeypatch.setattr(modal_train, "_ARTIFACT_STORE_PATH", str(tmp_path / "artifacts"))
    monkeypatch.setattr(
        modal_train, "artifact_store", type("V", (), {"commit": lambda self: committed.append(True)})()
    )

    written = modal_train._persist_artifact(
        b"PK\x03\x04 bundle",
        kind="bundles",
        suffix=".zip",
        meta={"base_model": "Qwen/Qwen2.5-14B-Instruct-AWQ", "augmentation_mode": "tag_pairs"},
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
    monkeypatch.setattr(modal_train, "_ARTIFACT_STORE_PATH", "/proc/nonexistent/artifacts")

    assert modal_train._persist_artifact(b"x", kind="bundles", suffix=".zip", meta={"base_model": "m"}) == ""


def test_degenerate_llm_output_is_rejected() -> None:
    """A repetition loop has no spaces, so word count alone lets it through.

    329 such pairs reached the shipped dataset, the worst 4,126 characters long.
    """
    degenerate = "search for lands battlefield" + "ation" * 800

    assert modal_train._parse_llm_queries(degenerate, max_queries=5) == []


def test_a_normal_query_survives_the_length_guard() -> None:
    assert modal_train._parse_llm_queries(
        "block with menace\ntap for green mana", max_queries=5
    ) == ["block with menace", "tap for green mana"]


def test_every_anchor_gets_the_full_budget(tmp_path) -> None:
    """Splitting the cap starved the bare name, which is the form users type."""
    payload = {
        "version": 3,
        "features": {"tag_pairs": False, "tag_descriptions": True, "template_queries": False, "llm_queries": False},
        "options": {"max_tag_desc_pairs_per_tag": 10},
        "abilities": [
            {"oracle_id": "o%d" % i, "face_ix": 0, "ability_ix": 0, "raw": "x", "text": "text %d" % i}
            for i in range(10)
        ],
        "card_names": [{"oracle_id": "o%d" % i, "face_ix": 0, "name": "n"} for i in range(10)],
        "tag_to_desc": {"mana dork": ["mana dork", "mana dork. Creatures that tap for mana"]},
        "tag_to_ability_ids": {"mana dork": [["o%d" % i, 0, 0] for i in range(10)]},
        "metadata": {"semantic_data_version": 7},
    }

    state, _ = modal_train._build_dataset_state(payload, augmentation_mode="tag_descriptions")

    bare = [p for p in state.direct_text_pairs if p[0] == "mana dork"]
    described = [p for p in state.direct_text_pairs if p[0].startswith("mana dork. ")]
    assert len(bare) == 10, "the bare name must get the whole budget, not half"
    assert len(described) == 10


def test_repeated_ability_text_is_not_taught_over_and_over() -> None:
    """Ability text deduplicates hard: "Flying." is 3,235 rows in the corpus.

    Whole-face text differed per card so this could not arise before. Without
    dedup a keyword-ish tag spends its entire budget on one identical string,
    and the serve side embeds one vector per distinct text anyway.
    """
    payload = {
        "version": 3,
        "features": {"tag_pairs": False, "tag_descriptions": True, "template_queries": False, "llm_queries": False},
        "options": {"max_tag_desc_pairs_per_tag": 50},
        "abilities": [
            {"oracle_id": "o%d" % i, "face_ix": 0, "ability_ix": 0, "raw": "Flying", "text": "flying."}
            for i in range(20)
        ],
        "card_names": [],
        "tag_to_desc": {"evasion": ["evasion"]},
        "tag_to_ability_ids": {"evasion": [["o%d" % i, 0, 0] for i in range(20)]},
        "metadata": {},
    }

    state, _ = modal_train._build_dataset_state(payload, augmentation_mode="tag_descriptions")

    assert len(state.direct_text_pairs) == 1
    assert state.simcse_examples == 1, "one self-pair per distinct text, not per row"


def test_a_tag_is_taught_only_the_abilities_it_was_attributed_to() -> None:
    """A card is a mana dork because of ONE of its abilities. Pairing the tag
    with the whole face taught it that `mana dork` also means "Flying"."""
    payload = {
        "version": 3,
        "features": {"tag_pairs": False, "tag_descriptions": True, "template_queries": False, "llm_queries": False},
        "options": {"max_tag_desc_pairs_per_tag": 50},
        "abilities": [
            {"oracle_id": "birds", "face_ix": 0, "ability_ix": 0, "raw": "Flying", "text": "flying."},
            {"oracle_id": "birds", "face_ix": 0, "ability_ix": 1, "raw": "{T}: Add one mana of any color.",
             "text": "tap this creature: add one mana of any color."},
        ],
        "card_names": [{"oracle_id": "birds", "face_ix": 0, "name": "Birds of Paradise"}],
        "tag_to_desc": {"mana dork": ["mana dork"]},
        # Attribution resolved the tag to ability 1 only.
        "tag_to_ability_ids": {"mana dork": [["birds", 0, 1]]},
        "metadata": {},
    }

    state, _ = modal_train._build_dataset_state(payload, augmentation_mode="tag_descriptions")

    positives = {positive for _anchor, positive, *_ in state.direct_text_pairs}
    assert positives == {"tap this creature: add one mana of any color."}
    assert "flying." not in positives


def test_warmup_is_a_fraction_of_optimizer_steps_not_examples() -> None:
    """The old formula divided an EXAMPLE count by 20 and passed it as steps,
    so 53% of every run was learning-rate warmup."""
    from ot_backend.semantic.modal_train import _WARMUP_FRACTION

    total, batch, epochs = 455_496, 32, 3
    total_steps = -(-total // batch) * epochs
    warmup = max(100, int(total_steps * _WARMUP_FRACTION))

    assert warmup / total_steps == pytest.approx(0.1, abs=0.01)
    assert warmup < total // 20, "must be far below the old example-derived value"


def test_the_chat_template_is_used_when_the_tokenizer_has_one() -> None:
    """An instruct model given a bare string does raw completion instead."""

    class _Tok:
        chat_template = "present"

        def apply_chat_template(self, messages, tokenize, add_generation_prompt):  # noqa: ANN001
            assert tokenize is False and add_generation_prompt is True
            assert [m["role"] for m in messages] == ["system", "user"]
            return "TEMPLATED"

    face = {"oracle_text": "{T}: Add {G}.", "text": "tap this creature: Add one green mana."}

    assert modal_train._build_llm_prompt(face, max_queries=5, tokenizer=_Tok()) == "TEMPLATED"


def test_a_tokenizer_without_a_template_falls_back_to_plain_text() -> None:
    face = {"oracle_text": "{T}: Add {G}.", "text": "x"}

    prompt = modal_train._build_llm_prompt(face, max_queries=5, tokenizer=None)

    assert "search query generator" in prompt
    assert "{T}: Add {G}." in prompt
    assert "/no_think" not in prompt, "a Qwen3 token is noise in a Qwen2.5 prompt"
