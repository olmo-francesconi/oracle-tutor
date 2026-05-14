"""Operator TUI for dataset / train / promote flows.

Usage (from backend/):
    uv run python -m scripts.tui
    uv run python -m scripts.tui --prod
    uv run ot-tui          # same thing, console-script entry
"""
from __future__ import annotations

from ot_backend.tui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
