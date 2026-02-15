from oracle_tutor_api.worker.data_builder import select_best_printing


def test_select_best_printing_prefers_paper_over_digital() -> None:
    paper_card = {"id": "1", "games": ["paper"], "released_at": "2020-01-01"}
    digital_card = {"id": "2", "games": ["mtgo"], "released_at": "2010-01-01"}
    
    # Even though digital is older, paper should win
    assert select_best_printing(paper_card, digital_card) == paper_card
    assert select_best_printing(digital_card, paper_card) == paper_card


def test_select_best_printing_prefers_older_release_date() -> None:
    old_card = {"id": "1", "games": ["paper"], "released_at": "2000-01-01"}
    new_card = {"id": "2", "games": ["paper"], "released_at": "2020-01-01"}
    
    assert select_best_printing(old_card, new_card) == old_card
    assert select_best_printing(new_card, old_card) == old_card


def test_select_best_printing_prefers_lower_collector_number_tiebreaker() -> None:
    # Same release date (e.g. same set)
    card_a = {"id": "1", "games": ["paper"], "released_at": "2020-01-01", "collector_number": "10"}
    card_b = {"id": "2", "games": ["paper"], "released_at": "2020-01-01", "collector_number": "20"}
    
    assert select_best_printing(card_a, card_b) == card_a
    assert select_best_printing(card_b, card_a) == card_a


def test_select_best_printing_handles_missing_fields_gracefully() -> None:
    card_a = {"id": "1"}
    card_b = {"id": "2"}
    
    # Deterministic fallback (returns first arg if equal preference)
    assert select_best_printing(card_a, card_b) == card_a
