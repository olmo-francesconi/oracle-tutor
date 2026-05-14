"""Pure rendering helpers for the rich-only TUI.

Each function takes plain state and returns a rich renderable. No I/O,
no key reading, no terminal mutation — only what to draw.
"""
from __future__ import annotations

from collections.abc import Sequence

from rich.align import Align
from rich.box import ROUNDED
from rich.console import Group, RenderableType
from rich.layout import Layout
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text

# Palette
_ACCENT = "#7dd3fc"        # cyan-300
_MUTED = "#94a3b8"         # slate-400
_BORDER = "#475569"        # slate-600
_INNER_BORDER = "#0ea5e9"  # sky-500
_SELECTED_BG = "#1e293b"   # slate-800
_SELECTED_FG = "#e0f2fe"   # sky-100

_SELECTED_LINE = Style(color=_SELECTED_FG, bgcolor=_SELECTED_BG, bold=True)
_CURSOR_GLYPH = "❯ "
_BLANK_GLYPH = "  "

# ---------------------------------------------------------------------------
# Outer chrome — wraps every screen
# ---------------------------------------------------------------------------


def chrome(
    *,
    title: str,
    env_label: str,
    body: RenderableType,
    footer: str,
    width: int,
    height: int,
) -> RenderableType:
    """Outer Panel with header / body / footer Layout, sized to fill the terminal.

    `width` and `height` must come from the live console — Rich needs them to
    clip the layout so the outer border isn't pushed off-screen.
    """
    header_left = Text()
    header_left.append("◆ ", style=_ACCENT)
    header_left.append("Oracle Tutor", style=f"bold {_SELECTED_FG}")
    header_left.append("  operator", style=f"dim {_MUTED}")
    header_right = Text(f"env  {env_label}", style=f"dim {_MUTED}", justify="right")

    header = Table.grid(expand=True, padding=(0, 1))
    header.add_column(justify="left", ratio=1)
    header.add_column(justify="right", ratio=1)
    header.add_row(header_left, header_right)

    footer_text = Text(footer, style=f"dim {_MUTED}")

    inner_panel = Panel(
        body,
        title=Text(f" {title} ", style=f"bold {_ACCENT}"),
        title_align="left",
        border_style=_INNER_BORDER,
        box=ROUNDED,
        padding=(1, 2),
    )

    inner_layout = Layout()
    header_layout = Layout(name="header", size=1)
    header_layout.update(header)
    body_layout = Layout(name="body", ratio=1)
    body_layout.update(inner_panel)
    footer_layout = Layout(name="footer", size=1)
    footer_layout.update(footer_text)
    inner_layout.split_column(header_layout, body_layout, footer_layout)

    return Panel(
        inner_layout,
        border_style=_BORDER,
        box=ROUNDED,
        padding=(0, 1),
        width=width,
        height=height,
    )


# ---------------------------------------------------------------------------
# Menu / radiolist
# ---------------------------------------------------------------------------


def render_menu(items: Sequence[tuple[str, str]], cursor: int, *, prompt: str | None = None) -> RenderableType:
    """Vertical menu. Items are (key, label). Cursor highlights one row."""
    lines: list[Text] = []
    if prompt:
        lines.append(Text(prompt, style=f"bold {_ACCENT}"))
        lines.append(Text(""))
    for i, (_, label) in enumerate(items):
        if i == cursor:
            line = Text()
            line.append(_CURSOR_GLYPH, style=_ACCENT)
            line.append(f" {label} ", style=_SELECTED_LINE)
        else:
            line = Text()
            line.append(_BLANK_GLYPH, style=_MUTED)
            line.append(f" {label} ", style=_MUTED)
        lines.append(line)
    return Group(*lines)


# ---------------------------------------------------------------------------
# Checkboxes
# ---------------------------------------------------------------------------


def render_checkboxes(
    items: Sequence[tuple[str, str]],
    cursor: int,
    selected: set[str],
    *,
    prompt: str | None = None,
) -> RenderableType:
    """Vertical checkbox list. Items are (key, label). selected = set of keys."""
    lines: list[Text] = []
    if prompt:
        lines.append(Text(prompt, style=f"bold {_ACCENT}"))
        lines.append(Text(""))
    for i, (key, label) in enumerate(items):
        is_cursor = i == cursor
        checked = key in selected
        glyph = "◉" if checked else "○"
        glyph_style = _ACCENT if checked else _MUTED
        line = Text()
        if is_cursor:
            line.append(_CURSOR_GLYPH, style=_ACCENT)
        else:
            line.append(_BLANK_GLYPH)
        line.append(f"{glyph} ", style=glyph_style)
        if is_cursor:
            line.append(f" {label} ", style=_SELECTED_LINE)
        else:
            line.append(f" {label} ", style=_MUTED)
        lines.append(line)
    return Group(*lines)


# ---------------------------------------------------------------------------
# Single-line text input
# ---------------------------------------------------------------------------


def render_input(label: str, value: str, *, hint: str | None = None) -> RenderableType:
    """Single-line text input with a blinking-style cursor at the end."""
    parts: list[RenderableType] = []
    parts.append(Text(label, style=f"bold {_ACCENT}"))
    parts.append(Text(""))
    input_text = Text()
    input_text.append(" ", style=_SELECTED_LINE)
    input_text.append(value, style=Style(color=_SELECTED_FG, bgcolor=_SELECTED_BG))
    input_text.append("▎", style=f"{_ACCENT} on {_SELECTED_BG}")
    input_text.append(" " * 60, style=Style(bgcolor=_SELECTED_BG))
    parts.append(input_text)
    if hint:
        parts.append(Text(""))
        parts.append(Text(hint, style=f"dim {_MUTED}"))
    return Group(*parts)


# ---------------------------------------------------------------------------
# Confirm (Y/N)
# ---------------------------------------------------------------------------


def render_confirm(prompt: str, summary_rows: Sequence[tuple[str, str]] | None = None) -> RenderableType:
    """Confirmation screen — prompt + optional summary table + Y/N hint."""
    parts: list[RenderableType] = [Text(prompt, style=f"bold {_ACCENT}"), Text("")]
    if summary_rows:
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="right", style=f"dim {_MUTED}")
        table.add_column(style=_SELECTED_FG)
        for k, v in summary_rows:
            table.add_row(k, v)
        parts.append(table)
        parts.append(Text(""))
    parts.append(Text("Y run    N / ESC cancel", style=f"dim {_MUTED}"))
    return Group(*parts)


# ---------------------------------------------------------------------------
# Generic row-cursor table
# ---------------------------------------------------------------------------


def render_row_table(
    *,
    columns: Sequence[str],
    rows: Sequence[Sequence[str]],
    cursor: int,
    empty_message: str = "(no rows)",
) -> RenderableType:
    if not rows:
        return Align.center(Text(empty_message, style=f"dim {_MUTED}"))
    table = Table(
        show_header=True,
        header_style=f"bold {_ACCENT}",
        expand=True,
        pad_edge=False,
        box=None,
        row_styles=None,
    )
    for col in columns:
        table.add_column(col, overflow="fold", style=_MUTED, header_style=f"bold {_ACCENT}")
    for i, row in enumerate(rows):
        style = _SELECTED_LINE if i == cursor else None
        table.add_row(*row, style=style)
    return table


# ---------------------------------------------------------------------------
# Key-value table (used for boot checks)
# ---------------------------------------------------------------------------


def render_kv_table(rows: Sequence[tuple[str, str, str, str]]) -> RenderableType:
    """rows: (glyph, name, detail, latency)."""
    table = Table(
        show_header=True,
        header_style=f"bold {_ACCENT}",
        expand=True,
        pad_edge=False,
        box=None,
    )
    table.add_column("", width=2)
    table.add_column("Check", style=_SELECTED_FG)
    table.add_column("Detail", overflow="fold", style=_MUTED)
    table.add_column("Latency", justify="right", style=_MUTED)
    for glyph, name, detail, latency in rows:
        table.add_row(glyph, name, detail, latency)
    return table


# ---------------------------------------------------------------------------
# Log view
# ---------------------------------------------------------------------------


def render_logs(lines: Sequence[str], *, summary: str | None = None, max_lines: int) -> RenderableType:
    visible = list(lines)[-max_lines:]
    body_lines: list[Text] = []
    if not visible:
        body_lines.append(Text("(waiting for output…)", style=f"dim {_MUTED}"))
    else:
        for line in visible:
            body_lines.append(Text(line, style=_MUTED, overflow="ellipsis", no_wrap=True))
    parts: list[RenderableType] = [Group(*body_lines)]
    if summary:
        parts.append(Text(""))
        parts.append(Text.from_markup(summary, style="bold"))
    return Group(*parts)
