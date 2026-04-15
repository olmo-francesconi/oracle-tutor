from __future__ import annotations

from ot_backend.embed import modal_train


def test_build_dataset_state_adds_llm_query_pairs(monkeypatch) -> None:
    monkeypatch.setattr("ot_backend.embed.modal_train.semantic_llm_model_name", lambda: "test-llm")
    monkeypatch.setattr(
        "ot_backend.embed.modal_train._generate_llm_query_pairs",
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
        "ot_backend.embed.modal_train.generate_template_queries",
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
    monkeypatch.setattr("ot_backend.embed.modal_train.generate_template_queries", lambda _text: [])

    selected = modal_train._select_llm_gap_faces(
        [
            {"oracle_text": "", "text": "emptyoracle"},
            {"oracle_text": "Draw a card.", "text": "Draw a card."},
        ],
        min_template_coverage=2,
        max_faces=10,
    )

    assert selected == [{"oracle_text": "Draw a card.", "text": "Draw a card."}]
