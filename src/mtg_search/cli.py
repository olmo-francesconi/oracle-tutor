import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import curses
except ImportError:  # pragma: no cover - curses may be unavailable on some OSes
    curses = None

from .card_data import (
    build_card_lookup_by_id,
    build_card_lookup_by_name,
    load_card_name_index,
    load_cards,
)
from .card_name_resolver import CardNameResolver

RANK_WEIGHT = 0.25


def _build_resolver_entries_from_cards(
    cards: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for card in cards:
        name = card.get("name")
        if not name:
            continue
        entry: Dict[str, Any] = {
            "name": name,
            "edhrec_rank": card.get("edhrec_rank"),
        }
        if card.get("id"):
            entry["id"] = card["id"]
        entries.append(entry)
    return entries


def main():
    print("Loading cards...")
    cards = load_cards()
    card_lookup_by_name = build_card_lookup_by_name(cards)
    card_lookup_by_id = build_card_lookup_by_id(cards)

    try:
        resolver_entries = load_card_name_index()
    except FileNotFoundError:
        resolver_entries = _build_resolver_entries_from_cards(cards)

    resolver = CardNameResolver(resolver_entries)
    name_to_id = {entry["name"]: entry["id"] for entry in resolver_entries if entry.get("id")}
    name_to_rank: Dict[str, Optional[int]] = {
        entry["name"]: entry.get("edhrec_rank")
        for entry in resolver_entries
    }

    if _supports_live_ui():
        try:
            _run_live_ui(
                resolver,
                name_to_id,
                name_to_rank,
                card_lookup_by_id,
                card_lookup_by_name,
            )
            return
        except Exception as exc:  # pragma: no cover - safety net for curses issues
            print(f"Live UI unavailable ({exc}). Falling back to basic prompt.")

    _run_basic_prompt(
        resolver,
        name_to_id,
        name_to_rank,
        card_lookup_by_id,
        card_lookup_by_name,
    )


def _supports_live_ui() -> bool:
    return (
        curses is not None
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    )


def _resolve_card(
    name: str,
    name_to_id: Dict[str, str],
    lookup_by_id: Dict[str, Dict[str, Any]],
    lookup_by_name: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    card_id = name_to_id.get(name)
    if card_id:
        card = lookup_by_id.get(card_id)
        if card:
            return card
    return lookup_by_name.get(name, {})


def _format_card_details(card: Dict[str, Any]) -> List[str]:
    card = card or {}
    if not card:
        return ["Card details unavailable locally."]

    lines: List[str] = []
    mana_cost = card.get("mana_cost", "")
    type_line = card.get("type_line", "Unknown type")
    oracle_text = card.get("oracle_text", "").strip()

    if mana_cost:
        lines.append(f"Mana Cost: {mana_cost}")
    lines.append(f"Type Line: {type_line}")
    if oracle_text:
        lines.append("Oracle Text:")
        lines.extend(oracle_text.splitlines())
    return lines


def _get_top_matches(
    text: str,
    resolver: CardNameResolver,
    name_to_id: Dict[str, str],
    name_to_rank: Dict[str, Optional[int]],
    lookup_by_id: Dict[str, Dict[str, Any]],
    lookup_by_name: Dict[str, Dict[str, Any]],
    limit: int = 5,
) -> List[Tuple[str, float, Optional[int], List[str]]]:
    stripped = text.strip()
    if not stripped:
        return []

    candidates = resolver.top_matches(
        stripped,
        limit=limit,
        rank_weight=RANK_WEIGHT,
    )
    
    results = []
    for name, similarity, _combined in candidates:
        card = _resolve_card(name, name_to_id, lookup_by_id, lookup_by_name)
        details = _format_card_details(card)
        rank = name_to_rank.get(name)
        results.append((name, similarity, rank, details))
    
    return results


def _run_basic_prompt(
    resolver: CardNameResolver,
    name_to_id: Dict[str, str],
    name_to_rank: Dict[str, Optional[int]],
    lookup_by_id: Dict[str, Dict[str, Any]],
    lookup_by_name: Dict[str, Dict[str, Any]],
) -> None:
    print("Ready. Type a card name (or 'q' to quit):")
    while True:
        text = input("> ")
        if text.strip().lower() in {"q", "quit", "exit"}:
            break
        _print_match(
            text,
            resolver,
            name_to_id,
            name_to_rank,
            lookup_by_id,
            lookup_by_name,
        )


def _print_match(
    text: str,
    resolver: CardNameResolver,
    name_to_id: Dict[str, str],
    name_to_rank: Dict[str, Optional[int]],
    lookup_by_id: Dict[str, Dict[str, Any]],
    lookup_by_name: Dict[str, Dict[str, Any]],
) -> Tuple[str, List[str]]:
    if not text.strip():
        print("Please provide at least one character.")
        return "", []

    matches = _get_top_matches(
        text,
        resolver,
        name_to_id,
        name_to_rank,
        lookup_by_id,
        lookup_by_name,
        limit=5,
    )
    if not matches:
        print("Sorry, I couldn't confidently match that card.")
        return "", []

    # Print best match details
    best_name, best_sim, best_rank, best_details = matches[0]
    rank_text = f"EDHREC rank {best_rank}" if best_rank else "EDHREC rank n/a"
    print(f"Best guess: {best_name} ({best_sim:.2%} similarity, {rank_text})")
    
    if len(matches) > 1:
        print("Other candidates:")
        for name, sim, rank, _ in matches[1:]:
            r_text = f"rank {rank}" if rank else "rank n/a"
            print(f"  - {name} ({sim:.2%}, {r_text})")

    for line in best_details:
        print(line)
    return best_name, best_details


def _run_live_ui(
    resolver: CardNameResolver,
    name_to_id: Dict[str, str],
    name_to_rank: Dict[str, Optional[int]],
    lookup_by_id: Dict[str, Dict],
    lookup_by_name: Dict[str, Dict[str, Any]],
) -> None:
    curses.wrapper(
        _live_ui_loop,
        resolver,
        name_to_id,
        name_to_rank,
        lookup_by_id,
        lookup_by_name,
    )


def _live_ui_loop(
    stdscr,
    resolver: CardNameResolver,
    name_to_id: Dict[str, str],
    name_to_rank: Dict[str, Optional[int]],
    lookup_by_id: Dict[str, Dict],
    lookup_by_name: Dict[str, Dict[str, Any]],
) -> None:
    curses.curs_set(1)
    stdscr.nodelay(False)
    stdscr.keypad(True)
    current_text = ""
    selected_index = 0
    match_count = 0

    while True:
        match_count = _render_screen(
            stdscr,
            current_text,
            resolver,
            name_to_id,
            name_to_rank,
            lookup_by_id,
            lookup_by_name,
            selected_index,
        )
        ch = stdscr.get_wch()
        if isinstance(ch, str):
            if ch in ("\x03", "\x04"):  # Ctrl-C / Ctrl-D
                raise KeyboardInterrupt
            if ch in ("\x1b",):  # ESC
                break
            if ch in ("\n", "\r"):
                current_text = ""
                selected_index = 0
                continue
            if ch in ("\x7f", "\b"):
                current_text = current_text[:-1]
                selected_index = 0
                continue
            if ch.isprintable():
                current_text += ch
                selected_index = 0
        elif ch == curses.KEY_BACKSPACE:
            current_text = current_text[:-1]
            selected_index = 0
        elif ch == curses.KEY_DOWN:
            if match_count > 0:
                selected_index = min(selected_index + 1, match_count - 1)
        elif ch == curses.KEY_UP:
            selected_index = max(selected_index - 1, 0)
        elif ch in (curses.KEY_EXIT, curses.KEY_END):
            break


def _render_screen(
    stdscr,
    text: str,
    resolver: CardNameResolver,
    name_to_id: Dict[str, str],
    name_to_rank: Dict[str, Optional[int]],
    lookup_by_id: Dict[str, Dict],
    lookup_by_name: Dict[str, Dict],
    selected_index: int = 0,
) -> int:
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()

    def put(row: int, content: str) -> None:
        if row < max_y:
            stdscr.addstr(row, 0, content[: max_x - 1])

    put(0, "MTG Search — type to update best guess (ESC to quit)")
    put(2, "Live mode: best match updates as you type. Use UP/DOWN to select.")

    visible_cols = max(0, max_x - 3)
    visible_text = text[-visible_cols:] if visible_cols else text
    input_line = f"> {visible_text}"
    display_input = input_line[: max_x - 1]
    put(4, display_input)

    match_lines, details, count = _describe_matches(
        text,
        resolver,
        name_to_id,
        name_to_rank,
        lookup_by_id,
        lookup_by_name,
        selected_index,
    )
    
    row = 6
    put(row, "Top matches:")
    row += 1
    
    for line in match_lines:
        if row >= max_y:
            break
        put(row, line)
        row += 1

    row += 1
    if row < max_y:
        put(row, "--- Details ---")
        row += 1
        
    for line in details:
        if row >= max_y:
            break
        put(row, line)
        row += 1

    cursor_col = min(len(display_input), max_x - 1)
    stdscr.move(4, cursor_col)
    stdscr.refresh()
    return count


def _describe_matches(
    text: str,
    resolver: CardNameResolver,
    name_to_id: Dict[str, str],
    name_to_rank: Dict[str, Optional[int]],
    lookup_by_id: Dict[str, Dict],
    lookup_by_name: Dict[str, Dict[str, Any]],
    selected_index: int = 0,
) -> Tuple[List[str], List[str], int]:
    stripped = text.strip()
    if not stripped:
        return (["(start typing...)"], [], 0)

    matches = _get_top_matches(
        stripped,
        resolver,
        name_to_id,
        name_to_rank,
        lookup_by_id,
        lookup_by_name,
        limit=5,
    )
    if not matches:
        return (["No confident match yet."], [], 0)
    
    count = len(matches)
    # Ensure index is within bounds for rendering
    idx = max(0, min(selected_index, count - 1))

    headings = []
    for i, (name, similarity, rank, _) in enumerate(matches):
        rank_text = f"rank {rank}" if rank else "rank n/a"
        prefix = "> " if i == idx else "  "
        headings.append(f"{prefix}{name} ({similarity:.0%}, {rank_text})")

    # Details for the selected match
    _, _, _, details = matches[idx]
    return (headings, details, count)


if __name__ == "__main__":
    main()
