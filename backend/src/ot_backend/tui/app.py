"""Oracle Tutor operator TUI — full-screen, bordered, rich-only.

One `rich.live.Live(screen=True)` covers the whole session. Each screen is a
function that renders into Live and loops on `read_key()` until it returns the
next screen name.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import keys as K
from .widgets import (
    chrome,
    render_checkboxes,
    render_confirm,
    render_input,
    render_kv_table,
    render_logs,
    render_menu,
    render_row_table,
)

if TYPE_CHECKING:
    from rich.console import RenderableType
    from rich.live import Live

logger = logging.getLogger("ot_backend.tui")

_STATUS_GLYPHS = {
    "ok": "[green]✓[/]",
    "warn": "[yellow]![/]",
    "fail": "[red]✗[/]",
    "skipped": "[dim]–[/]",
    "pending": "[dim]…[/]",
}
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Sentinels for LLM build:
# - max_faces is a hard `>= max_faces: break` check inside modal_train, so a value
#   larger than the total face count (~30k) means "no cap".
# - min_template_coverage skips a face when its template-query count is >= the value,
#   so a value larger than any possible coverage means "never skip".
_LLM_FACES_UNLIMITED = 10_000_000
_LLM_COVERAGE_REGARDLESS = 1_000_000


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ot-tui", description="Oracle Tutor operator TUI.")
    parser.add_argument("--prod", action="store_true", default=False, help="Load backend/.env.prod instead of backend/.env.")
    parser.add_argument("--debug-keys", action="store_true", default=False, help="Run a keyboard probe instead of the TUI — prints every key read until Q.")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    from ._env import load_env

    load_env(prod=args.prod)
    if args.debug_keys:
        return _debug_keys()
    return _run(prod=args.prod)


def _debug_keys() -> int:
    print("RawTTY keyboard probe. Press keys to see what read_key() returns. Press q to quit.")
    print("Try the arrow keys you expect to work in the menu.")
    with K.RawTTY():
        while True:
            key = K.read_key()
            sys.stdout.write(f"\rkey = {key!r:<20}\n")
            sys.stdout.flush()
            if key == "q" or key == K.KEY_CTRL_C:
                return 0


def _run(*, prod: bool) -> int:
    from rich.console import Console
    from rich.live import Live

    console = Console()
    env_label = ".env.prod" if prod else ".env"

    with Live(console=console, screen=True, auto_refresh=False, redirect_stdout=False, redirect_stderr=False) as live, K.RawTTY():
        ctx = AppContext(live=live, env_label=env_label)
        next_screen: str | None = "boot"
        while next_screen:
            handler = _SCREENS.get(next_screen)
            if handler is None:
                break
            next_screen = handler(ctx)
    return 0


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


class AppContext:
    def __init__(self, *, live: "Live", env_label: str) -> None:
        self.live = live
        self.env_label = env_label
        # Cached state between screens
        self.check_results: list[dict[str, object]] = []  # serialised CheckResult
        self.preselected_dataset_id: str | None = None
        self.preselected_model_id: str | None = None
        self._last_frame: tuple[str, "RenderableType", str] | None = None

    def draw(self, *, title: str, body: "RenderableType", footer: str) -> None:
        self._last_frame = (title, body, footer)
        self._render_current()

    def _render_current(self) -> None:
        if self._last_frame is None:
            return
        title, body, footer = self._last_frame
        size = self.live.console.size
        self.live.update(
            chrome(
                title=title,
                env_label=self.env_label,
                body=body,
                footer=footer,
                width=size.width,
                height=size.height,
            ),
            refresh=True,
        )

    def wait_key(self) -> str:
        """Block on a keypress, redrawing the last frame whenever the terminal is resized."""
        last_size = self.live.console.size
        while True:
            key = K.read_key(timeout=0.15)
            if key is not None:
                return key
            cur = self.live.console.size
            if cur != last_size:
                last_size = cur
                self._render_current()


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def _prompt_text(
    ctx: AppContext,
    *,
    title: str,
    label: str,
    default: str = "",
    hint: str | None = None,
    allow_chars: Callable[[str], bool] = lambda ch: ch.isprintable(),
    allow_empty: bool = False,
    cancel_returns: object = "menu",
) -> tuple[str, object] | None:
    """Render a single-line text input. ENTER accepts current value, ESC cancels.

    Returns (value, None) on accept or (value, cancel_returns) if cancelled.
    """
    value = default
    while True:
        body = render_input(label, value, hint=hint)
        ctx.draw(title=title, body=body, footer="  [ENTER] next    [ESC] cancel")
        key = ctx.wait_key()
        if key == K.KEY_ENTER:
            if not value and not allow_empty:
                continue
            return (value, None)
        if key == K.KEY_ESC:
            return (value, cancel_returns)
        if key == K.KEY_CTRL_C:
            return None
        if key == K.KEY_BACKSPACE:
            value = value[:-1]
        elif key and len(key) == 1 and allow_chars(key):
            value += key


def _prompt_int(ctx: AppContext, *, title: str, label: str, default: int, hint: str | None = None) -> int | None:
    """Numeric prompt. Returns None if cancelled."""
    res = _prompt_text(
        ctx,
        title=title,
        label=label,
        default=str(default),
        hint=hint or f"positive integer, default {default}.",
        allow_chars=str.isdigit,
    )
    if res is None or res[1] is not None:
        return None
    value, _ = res
    try:
        n = int(value)
    except ValueError:
        return None
    return n if n > 0 else None


def _prompt_float(ctx: AppContext, *, title: str, label: str, default: float, hint: str | None = None) -> float | None:
    res = _prompt_text(
        ctx,
        title=title,
        label=label,
        default=str(default),
        hint=hint or f"float, default {default}.",
        allow_chars=lambda ch: ch.isdigit() or ch == ".",
    )
    if res is None or res[1] is not None:
        return None
    value, _ = res
    try:
        return float(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Boot screen — connection checks
# ---------------------------------------------------------------------------


def _format_check_rows(results: Sequence[dict[str, object]], *, spinner_frame: str) -> list[tuple[str, str, str, str]]:
    names = ("Database", "Artifact storage", "API", "Modal", "Cloudflare Access")
    by_name = {r["name"]: r for r in results}
    rows: list[tuple[str, str, str, str]] = []
    for name in names:
        r = by_name.get(name)
        if r is None:
            rows.append((f"[cyan]{spinner_frame}[/]", name, "running…", "—"))
            continue
        status = str(r.get("status", "pending"))
        raw_latency = r.get("latency_ms")
        latency_ms = int(raw_latency) if isinstance(raw_latency, (int, float)) else 0
        rows.append((
            _STATUS_GLYPHS.get(status, "?"),
            name,
            str(r.get("detail") or "—"),
            f"{latency_ms} ms" if latency_ms else "—",
        ))
    return rows


def boot_screen(ctx: AppContext) -> str | None:
    from .checks import run_all_checks_streaming

    results: list[dict[str, object]] = []
    done = threading.Event()

    def worker() -> None:
        def collect(r) -> None:
            results.append({"name": r.name, "status": r.status, "detail": r.detail, "latency_ms": r.latency_ms})
        asyncio.run(run_all_checks_streaming(collect))
        done.set()

    threading.Thread(target=worker, daemon=True).start()

    spinner_i = 0
    while not done.is_set():
        body = render_kv_table(_format_check_rows(results, spinner_frame=_SPINNER_FRAMES[spinner_i % len(_SPINNER_FRAMES)]))
        ctx.draw(title="Connection checks", body=body, footer="  please wait…")
        spinner_i += 1
        if K.read_key(timeout=0.08) == K.KEY_CTRL_C:
            return None

    ctx.check_results = results
    failures = sum(1 for r in results if r.get("status") == "fail")
    summary = "[green]all green[/] — press ENTER" if failures == 0 else f"[red]{failures} failing[/] — fix env or press ENTER to continue anyway"

    while True:
        body = render_kv_table(_format_check_rows(results, spinner_frame=" "))
        ctx.draw(title="Connection checks", body=body, footer=f"  {summary}    [ENTER] continue    [R] re-run    [Q] quit")
        key = ctx.wait_key()
        if key in (K.KEY_ENTER, " "):
            return "menu"
        if key == "q" or key == K.KEY_CTRL_C:
            return None
        if key == "r":
            return "boot"


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------


_MENU_ITEMS: list[tuple[str, str]] = [
    ("datasets", "Browse datasets"),
    ("models", "Browse models"),
    ("build", "Build dataset"),
    ("train", "Train model"),
    ("promote", "Promote model"),
    ("storage", "Storage audit & sync"),
    ("admin_ips", "Admin IP bans"),
    ("boot", "Re-run connection checks"),
    ("quit", "Quit"),
]


def menu_screen(ctx: AppContext) -> str | None:
    cursor = 0
    while True:
        body = render_menu(_MENU_ITEMS, cursor)
        ctx.draw(title="Menu", body=body, footer="  [↑/↓] move    [ENTER] select    [Q] quit")
        key = ctx.wait_key()
        if key == K.KEY_UP:
            cursor = (cursor - 1) % len(_MENU_ITEMS)
        elif key == K.KEY_DOWN:
            cursor = (cursor + 1) % len(_MENU_ITEMS)
        elif key == K.KEY_ENTER:
            target = _MENU_ITEMS[cursor][0]
            return None if target == "quit" else target
        elif key == "q" or key == K.KEY_CTRL_C:
            return None


# ---------------------------------------------------------------------------
# Datasets browser
# ---------------------------------------------------------------------------


def _load_datasets() -> list[dict[str, object]]:
    from ot_backend.core.database import SessionLocal
    from ot_backend.semantic.dataset_registry import list_semantic_datasets

    with SessionLocal() as db:
        rows = list_semantic_datasets(db)
        return [
            {
                "id": d.id,
                "slug": d.slug,
                "augmentation_mode": d.augmentation_mode,
                "status": d.status,
                "source_semantic_data_version": d.source_semantic_data_version,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "config_json": d.config_json,
                "metrics_json": d.metrics_json,
                "error_message": d.error_message,
                "artifacts": [
                    {"kind": a.artifact_kind, "object_key": a.object_key, "sha256": (a.sha256 or "")[:12], "size_bytes": a.size_bytes}
                    for a in d.artifacts
                ],
            }
            for d in rows
        ]


def datasets_screen(ctx: AppContext) -> str | None:
    from rich.console import Group
    from rich.text import Text

    try:
        rows = _load_datasets()
    except Exception as exc:  # noqa: BLE001
        return _error_screen(ctx, "Datasets", f"{type(exc).__name__}: {exc}")

    cursor = 0
    inspecting = False
    while True:
        if inspecting and rows:
            payload = rows[cursor]
            body = Group(
                Text(f"slug={payload['slug']}  id={payload['id']}", style="bold"),
                Text(""),
                Text(json.dumps(payload, indent=2, default=str)),
            )
            footer = "  [ESC] back to list    [Q] quit"
        else:
            columns = ("Slug", "ID", "Augmentation", "Status", "Created")
            display_rows = [
                (
                    str(p["slug"]),
                    str(p["id"])[:8],
                    str(p["augmentation_mode"] or "none"),
                    str(p["status"]),
                    (str(p["created_at"]) or "")[:19],
                )
                for p in rows
            ]
            body = render_row_table(columns=columns, rows=display_rows, cursor=cursor, empty_message="No datasets registered yet — press B to build one.")
            footer = "  [↑/↓] move    [ENTER] inspect    [B] build new    [T] train from selected    [ESC] menu"

        ctx.draw(title=f"Datasets ({len(rows)})", body=body, footer=footer)
        key = ctx.wait_key()
        if inspecting:
            if key in (K.KEY_ESC, K.KEY_ENTER):
                inspecting = False
            elif key == "q" or key == K.KEY_CTRL_C:
                return None
            continue
        if key == K.KEY_UP and rows:
            cursor = (cursor - 1) % len(rows)
        elif key == K.KEY_DOWN and rows:
            cursor = (cursor + 1) % len(rows)
        elif key == K.KEY_ENTER and rows:
            inspecting = True
        elif key == "b":
            return "build"
        elif key == "t" and rows:
            ctx.preselected_dataset_id = str(rows[cursor]["id"])
            return "train"
        elif key == K.KEY_ESC:
            return "menu"
        elif key == "q" or key == K.KEY_CTRL_C:
            return None


# ---------------------------------------------------------------------------
# Models browser
# ---------------------------------------------------------------------------


def _load_models() -> tuple[list[dict[str, object]], str | None]:
    from ot_backend.core.database import SessionLocal
    from ot_backend.semantic.model_registry import (
        count_semantic_model_embeddings_batch,
        get_active_semantic_model_id,
        list_semantic_models,
    )

    with SessionLocal() as db:
        rows = list_semantic_models(db)
        counts = count_semantic_model_embeddings_batch(db, [m.id for m in rows])
        active_id = get_active_semantic_model_id(db)
        return (
            [
                {
                    "id": m.id,
                    "slug": m.slug,
                    "base_model": m.base_model,
                    "status": m.status,
                    "is_active": bool(m.is_active),
                    "embedding_dim": m.embedding_dim,
                    "embedding_count": counts.get(m.id, 0),
                    "dataset_id": m.dataset_id,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "activated_at": m.activated_at.isoformat() if m.activated_at else None,
                    "config_json": m.config_json,
                    "metrics_json": m.metrics_json,
                    "error_message": m.error_message,
                    "artifacts": [
                        {"kind": a.artifact_kind, "object_key": a.object_key, "sha256": (a.sha256 or "")[:12], "size_bytes": a.size_bytes}
                        for a in m.artifacts
                    ],
                }
                for m in rows
            ],
            active_id,
        )


def models_screen(ctx: AppContext) -> str | None:
    from rich.console import Group
    from rich.text import Text

    try:
        rows, active_id = _load_models()
    except Exception as exc:  # noqa: BLE001
        return _error_screen(ctx, "Models", f"{type(exc).__name__}: {exc}")

    cursor = 0
    inspecting = False
    while True:
        if inspecting and rows:
            payload = rows[cursor]
            body = Group(
                Text(f"slug={payload['slug']}  id={payload['id']}", style="bold"),
                Text(""),
                Text(json.dumps(payload, indent=2, default=str)),
            )
            footer = "  [ESC] back to list    [Q] quit"
        else:
            columns = ("Slug", "ID", "Base", "Status", "★", "Embeddings", "Created")
            display_rows = [
                (
                    str(p["slug"]),
                    str(p["id"])[:8],
                    str(p["base_model"]).split("/")[-1],
                    str(p["status"]),
                    "★" if p["id"] == active_id else "",
                    str(p["embedding_count"]),
                    (str(p["created_at"]) or "")[:19],
                )
                for p in rows
            ]
            body = render_row_table(columns=columns, rows=display_rows, cursor=cursor, empty_message="No models registered yet — press T to train one.")
            footer = "  [↑/↓] move    [ENTER] inspect    [T] train new    [P] promote selected    [ESC] menu"

        ctx.draw(title=f"Models ({len(rows)})", body=body, footer=footer)
        key = ctx.wait_key()
        if inspecting:
            if key in (K.KEY_ESC, K.KEY_ENTER):
                inspecting = False
            elif key == "q" or key == K.KEY_CTRL_C:
                return None
            continue
        if key == K.KEY_UP and rows:
            cursor = (cursor - 1) % len(rows)
        elif key == K.KEY_DOWN and rows:
            cursor = (cursor + 1) % len(rows)
        elif key == K.KEY_ENTER and rows:
            inspecting = True
        elif key == "t":
            return "train"
        elif key == "p" and rows:
            ctx.preselected_model_id = str(rows[cursor]["id"])
            return "promote"
        elif key == K.KEY_ESC:
            return "menu"
        elif key == "q" or key == K.KEY_CTRL_C:
            return None


# ---------------------------------------------------------------------------
# Build dataset wizard
# ---------------------------------------------------------------------------


def build_screen(ctx: AppContext) -> str | None:
    from ot_backend.semantic.train_options import (
        DEFAULT_TRAIN_AUGMENTATION_KEYS,
        TRAIN_AUGMENTATION_OPTIONS,
        serialize_train_augmentation_mode,
    )

    slug = ""
    aug_items = [(opt.key, f"{opt.key} — {opt.description}") for opt in TRAIN_AUGMENTATION_OPTIONS]
    selected = set(DEFAULT_TRAIN_AUGMENTATION_KEYS)
    aug_cursor = 0

    # Step 1: slug
    while True:
        body = render_input("Dataset slug (--name)", slug, hint="Unique identifier for the dataset. Used in the registry and as part of the dataset artifact key.")
        ctx.draw(title="Build dataset — step 1/3: slug", body=body, footer="  [ENTER] next    [ESC] cancel")
        key = ctx.wait_key()
        if key == K.KEY_ENTER:
            if not slug.strip():
                continue
            slug = slug.strip()
            break
        if key == K.KEY_ESC:
            return "menu"
        if key == K.KEY_CTRL_C:
            return None
        if key == K.KEY_BACKSPACE:
            slug = slug[:-1]
        elif key and len(key) == 1 and key.isprintable():
            slug += key

    # Step 2: augmentations
    while True:
        body = render_checkboxes(aug_items, aug_cursor, selected, prompt="Toggle augmentations:")
        ctx.draw(title="Build dataset — step 2/3: augmentations", body=body, footer="  [↑/↓] move    [SPACE] toggle    [ENTER] next    [ESC] cancel")
        key = ctx.wait_key()
        if key == K.KEY_UP:
            aug_cursor = (aug_cursor - 1) % len(aug_items)
        elif key == K.KEY_DOWN:
            aug_cursor = (aug_cursor + 1) % len(aug_items)
        elif key == K.KEY_SPACE:
            current_key = aug_items[aug_cursor][0]
            selected.symmetric_difference_update({current_key})
        elif key == K.KEY_ENTER:
            break
        elif key == K.KEY_ESC:
            return "menu"
        elif key == K.KEY_CTRL_C:
            return None

    augmentation_mode = serialize_train_augmentation_mode(sorted(selected))
    llm_selected = "llm_queries" in selected

    # Step 3: tag-pair tunables (always, ENTER through defaults).
    max_tag_pairs_per_tag = _prompt_int(
        ctx,
        title="Build dataset — max_tag_pairs_per_tag",
        label="max_tag_pairs_per_tag",
        default=50,
        hint="Cap on positive face-pairs sampled from each shared-tag group. Higher = more training signal but more redundancy.  default 50",
    )
    if max_tag_pairs_per_tag is None:
        return "menu"
    max_tag_pair_group_size = _prompt_int(
        ctx,
        title="Build dataset — max_tag_pair_group_size",
        label="max_tag_pair_group_size",
        default=5,
        hint="Minimum faces a tag must have before it contributes any tag-pair examples. Smaller = more tags qualify, noisier pairs.  default 5",
    )
    if max_tag_pair_group_size is None:
        return "menu"
    max_tag_desc_pairs_per_tag = _prompt_int(
        ctx,
        title="Build dataset — max_tag_desc_pairs_per_tag",
        label="max_tag_desc_pairs_per_tag",
        default=50,
        hint="Cap on (tag-description anchor, face) pairs sampled per tag. Drives the tag_descriptions augmentation volume.  default 50",
    )
    if max_tag_desc_pairs_per_tag is None:
        return "menu"

    # Step 4: LLM tunables (only when llm_queries augmentation is selected).
    llm_config: dict[str, object] | None = None
    llm_display: dict[str, str] = {}
    if llm_selected:
        res = _prompt_text(
            ctx,
            title="Build dataset — LLM model",
            label="llm.model_name",
            default="Qwen/Qwen2.5-7B-Instruct",
            hint="HuggingFace model id used on Modal to generate synthetic search queries from card oracle text.",
        )
        if res is None or res[1] is not None:
            return "menu"
        llm_model_name, _ = res
        llm_max_queries_per_face = _prompt_int(
            ctx,
            title="Build dataset — LLM max_queries_per_face",
            label="llm.max_queries_per_face",
            default=3,
            hint="Number of synthetic queries the LLM produces per card face. Multiplies per-face cost.  default 3",
        )
        if llm_max_queries_per_face is None:
            return "menu"
        max_faces_res = _prompt_text(
            ctx,
            title="Build dataset — LLM max_faces",
            label="llm.max_faces",
            default="2500",
            hint='Hard cap on total faces sent through the LLM. Type a positive integer, or "all" to LLM-augment every face (no cap).  default 2500',
            allow_chars=lambda ch: ch.isalnum(),
        )
        if max_faces_res is None or max_faces_res[1] is not None:
            return "menu"
        llm_max_faces_display = max_faces_res[0].strip().lower()
        if llm_max_faces_display == "all":
            llm_max_faces_value = _LLM_FACES_UNLIMITED
        else:
            try:
                llm_max_faces_value = int(llm_max_faces_display)
            except ValueError:
                llm_max_faces_value = -1
            if llm_max_faces_value <= 0:
                return "menu"

        coverage_res = _prompt_text(
            ctx,
            title="Build dataset — LLM min_template_coverage",
            label="llm.min_template_coverage",
            default="2",
            hint='Skip faces already covered by at least this many template-generated queries. Type a non-negative integer, or "all" to LLM-augment regardless of existing coverage.  default 2',
            allow_chars=lambda ch: ch.isalnum(),
        )
        if coverage_res is None or coverage_res[1] is not None:
            return "menu"
        llm_min_coverage_display = coverage_res[0].strip().lower()
        if llm_min_coverage_display == "all":
            llm_min_template_coverage_value = _LLM_COVERAGE_REGARDLESS
        else:
            try:
                llm_min_template_coverage_value = int(llm_min_coverage_display)
            except ValueError:
                llm_min_template_coverage_value = -1
            if llm_min_template_coverage_value < 0:
                return "menu"
        llm_temperature = _prompt_float(
            ctx,
            title="Build dataset — LLM temperature",
            label="llm.temperature",
            default=0.6,
            hint="LLM sampling temperature. Lower = more deterministic queries, higher = more varied / noisier.  default 0.6",
        )
        if llm_temperature is None:
            return "menu"
        llm_max_tokens = _prompt_int(
            ctx,
            title="Build dataset — LLM max_tokens",
            label="llm.max_tokens",
            default=500,
            hint="Maximum output tokens per LLM call. Higher = more headroom for long query lists.  default 500",
        )
        if llm_max_tokens is None:
            return "menu"
        llm_config = {
            "model_name": llm_model_name,
            "max_queries_per_face": llm_max_queries_per_face,
            "max_faces": llm_max_faces_value,
            "min_template_coverage": llm_min_template_coverage_value,
            "temperature": llm_temperature,
            "max_tokens": llm_max_tokens,
        }
        llm_display = {
            "model_name": llm_model_name,
            "max_queries_per_face": str(llm_max_queries_per_face),
            "max_faces": "all" if llm_max_faces_value >= _LLM_FACES_UNLIMITED else str(llm_max_faces_value),
            "min_template_coverage": "all (LLM-augment every face)" if llm_min_template_coverage_value >= _LLM_COVERAGE_REGARDLESS else str(llm_min_template_coverage_value),
            "temperature": str(llm_temperature),
            "max_tokens": str(llm_max_tokens),
        }

    summary_rows: list[tuple[str, str]] = [
        ("slug", slug),
        ("augmentation", augmentation_mode or "none"),
        ("max_tag_pairs_per_tag", str(max_tag_pairs_per_tag)),
        ("max_tag_pair_group_size", str(max_tag_pair_group_size)),
        ("max_tag_desc_pairs_per_tag", str(max_tag_desc_pairs_per_tag)),
    ]
    if llm_config:
        for k, v in llm_display.items():
            summary_rows.append((f"llm.{k}", v))

    body = render_confirm("Run build_dataset with these inputs?", summary_rows=summary_rows)
    ctx.draw(title="Build dataset — confirm", body=body, footer="  [Y] run    [N/ESC] cancel")
    while True:
        key = ctx.wait_key()
        if key == "y":
            break
        if key in ("n", K.KEY_ESC):
            return "menu"
        if key == K.KEY_CTRL_C:
            return None

    tag_pair_tunables = {
        "max_tag_pairs_per_tag": max_tag_pairs_per_tag,
        "max_tag_pair_group_size": max_tag_pair_group_size,
        "max_tag_desc_pairs_per_tag": max_tag_desc_pairs_per_tag,
    }
    return _run_with_logs(
        ctx,
        label=f"build dataset {slug}",
        fn=lambda: _do_build_dataset(
            slug=slug,
            augmentation_mode=augmentation_mode,
            tag_pair_tunables=tag_pair_tunables,
            llm_config=llm_config,
        ),
        next_screen="menu",
    )


def _do_build_dataset(
    *,
    slug: str,
    augmentation_mode: str,
    tag_pair_tunables: dict[str, int],
    llm_config: dict[str, object] | None,
) -> str:
    from ot_backend.core.database import SessionLocal
    from ot_backend.semantic.dataset_registry import (
        create_semantic_dataset,
        semantic_dataset_artifact_keys,
        semantic_dataset_summary_metrics,
    )
    from ot_backend.semantic.dataset_service import (
        build_training_dataset_build_payload,
        build_training_dataset_state,
        serialize_training_dataset,
    )
    from ot_backend.semantic.semantic_state import build_training_dataset_metadata
    from ot_backend.semantic.train_options import TRAIN_AUGMENTATION_LLM_QUERIES, parse_train_augmentation_mode

    lg = logging.getLogger("ot_backend.semantic.scripts.build_dataset")
    lg.info("Building dataset. slug=%s augmentation=%s tunables=%s", slug, augmentation_mode, tag_pair_tunables)
    selected = set(parse_train_augmentation_mode(augmentation_mode))

    if TRAIN_AUGMENTATION_LLM_QUERIES in selected:
        lg.info("LLM augmentation selected — running Modal dataset build. llm=%s", llm_config)
        with SessionLocal() as db:
            payload_dict = build_training_dataset_build_payload(
                db,
                augmentation_mode=augmentation_mode,
                **tag_pair_tunables,
            )
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
        dataset_bytes = _run_modal_dataset_build(payload_bytes, augmentation_mode, llm_config=llm_config)
    else:
        with SessionLocal() as db:
            state = build_training_dataset_state(
                db,
                augmentation_mode=augmentation_mode,
                **tag_pair_tunables,
            )
            metadata = build_training_dataset_metadata(db)
        dataset_bytes = serialize_training_dataset(state, metadata=metadata)

    with SessionLocal() as db:
        dataset = create_semantic_dataset(
            db,
            slug=slug,
            augmentation_mode=augmentation_mode,
            dataset_bytes=dataset_bytes,
            metrics_json=semantic_dataset_summary_metrics(dataset_bytes),
        )
        artifact_keys = semantic_dataset_artifact_keys(db, dataset.id)
    lg.info("Dataset created. id=%s slug=%s", dataset.id, slug)
    return f"id={dataset.id}  artifacts: " + ", ".join(f"{k}={v}" for k, v in artifact_keys.items())


def _run_modal_dataset_build(
    payload: bytes,
    augmentation_mode: str,
    *,
    llm_config: dict[str, object] | None,
) -> bytes:
    from importlib import import_module

    from ot_backend.core.config import (
        modal_client_configured,
        modal_environment_name,
        semantic_llm_max_faces,
        semantic_llm_max_queries_per_face,
        semantic_llm_max_tokens,
        semantic_llm_min_template_coverage,
        semantic_llm_model_name,
        semantic_llm_temperature,
    )

    if not modal_client_configured():
        raise RuntimeError("Modal credentials missing. Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET.")
    modal_train = import_module("ot_backend.semantic.modal_train")
    build_fn = modal_train.build_dataset
    app = modal_train.app
    effective = llm_config or {
        "model_name": semantic_llm_model_name(),
        "max_queries_per_face": semantic_llm_max_queries_per_face(),
        "max_faces": semantic_llm_max_faces(),
        "min_template_coverage": semantic_llm_min_template_coverage(),
        "temperature": semantic_llm_temperature(),
        "max_tokens": semantic_llm_max_tokens(),
    }
    with app.run(environment_name=modal_environment_name()):
        return build_fn.remote(payload, augmentation_mode, effective)


# ---------------------------------------------------------------------------
# Train model wizard
# ---------------------------------------------------------------------------


def train_screen(ctx: AppContext) -> str | None:
    from ot_backend.semantic.base_model_catalog import list_semantic_base_models

    base_models = list_semantic_base_models()

    # Step 1: training mode — skip-fine-tune first so the fast path can short-circuit later prompts.
    mode_items: list[tuple[str, str]] = [
        ("skip", "Skip fine-tune — export base model as-is (no dataset required)"),
        ("train", "Run fine-tune — Modal training with epochs / batch size (requires a dataset)"),
    ]
    mode_cursor = 0
    while True:
        body = render_menu(mode_items, mode_cursor, prompt="Training mode")
        ctx.draw(title="Train model — mode", body=body, footer="  [↑/↓] move    [ENTER] select    [ESC] cancel")
        key = ctx.wait_key()
        if key == K.KEY_UP:
            mode_cursor = (mode_cursor - 1) % len(mode_items)
        elif key == K.KEY_DOWN:
            mode_cursor = (mode_cursor + 1) % len(mode_items)
        elif key == K.KEY_ENTER:
            skip = mode_items[mode_cursor][0] == "skip"
            break
        elif key == K.KEY_ESC:
            return "menu"
        elif key == K.KEY_CTRL_C:
            return None

    # Step 2 (fine-tune only): pick dataset. Skip-fine-tune synthesises face data on the fly.
    dataset = None
    if not skip:
        from ot_backend.core.database import SessionLocal
        from ot_backend.semantic.dataset_registry import list_semantic_datasets

        try:
            with SessionLocal() as db:
                datasets = list_semantic_datasets(db)
        except Exception as exc:  # noqa: BLE001
            return _error_screen(ctx, "Train model", f"{type(exc).__name__}: {exc}")

        if not datasets:
            return _error_screen(ctx, "Train model", "No datasets registered. Build one first (or use Skip fine-tune).")

        cursor = 0
        if ctx.preselected_dataset_id:
            for i, d in enumerate(datasets):
                if d.id == ctx.preselected_dataset_id:
                    cursor = i
                    break
            ctx.preselected_dataset_id = None
        while True:
            columns = ("Slug", "ID", "Augmentation", "Created")
            rows = [(d.slug, str(d.id)[:8], d.augmentation_mode or "none", (d.created_at.isoformat() if d.created_at else "")[:19]) for d in datasets]
            body = render_row_table(columns=columns, rows=rows, cursor=cursor)
            ctx.draw(title="Train model — pick dataset", body=body, footer="  [↑/↓] move    [ENTER] select    [ESC] cancel")
            key = ctx.wait_key()
            if key == K.KEY_UP:
                cursor = (cursor - 1) % len(datasets)
            elif key == K.KEY_DOWN:
                cursor = (cursor + 1) % len(datasets)
            elif key == K.KEY_ENTER:
                dataset = datasets[cursor]
                break
            elif key == K.KEY_ESC:
                return "menu"
            elif key == K.KEY_CTRL_C:
                return None

    # Step 3: slug
    slug = ""
    while True:
        body = render_input("Model slug (--slug)", slug, hint="Unique identifier for the trained model. Used in the model registry and as part of the bundle artifact key.")
        ctx.draw(title="Train model — model slug", body=body, footer="  [ENTER] next    [ESC] cancel")
        key = ctx.wait_key()
        if key == K.KEY_ENTER and slug.strip():
            slug = slug.strip()
            break
        if key == K.KEY_ESC:
            return "menu"
        if key == K.KEY_CTRL_C:
            return None
        if key == K.KEY_BACKSPACE:
            slug = slug[:-1]
        elif key and len(key) == 1 and key.isprintable():
            slug += key

    # Step 4: pick base model
    bm_cursor = 0
    while True:
        columns = ("Key", "Label", "Dim")
        rows = [(spec.key, spec.label, str(spec.embedding_dim)) for spec in base_models]
        body = render_row_table(columns=columns, rows=rows, cursor=bm_cursor)
        ctx.draw(title="Train model — base model", body=body, footer="  [↑/↓] move    [ENTER] select    [ESC] cancel")
        key = ctx.wait_key()
        if key == K.KEY_UP:
            bm_cursor = (bm_cursor - 1) % len(base_models)
        elif key == K.KEY_DOWN:
            bm_cursor = (bm_cursor + 1) % len(base_models)
        elif key == K.KEY_ENTER:
            base_spec = base_models[bm_cursor]
            break
        elif key == K.KEY_ESC:
            return "menu"
        elif key == K.KEY_CTRL_C:
            return None

    # Epochs + batch size only when actually fine-tuning. Defaults match the standalone script.
    epochs = 3
    batch_size = 32
    if not skip:
        epochs_str = "3"
        while True:
            body = render_input("Epochs (--epochs)", epochs_str, hint="Full passes over the training dataset. More epochs ≈ better fit but longer Modal runtime and risk of overfitting.  default 3")
            ctx.draw(title="Train model — epochs", body=body, footer="  [ENTER] next    [ESC] cancel")
            key = ctx.wait_key()
            if key == K.KEY_ENTER and epochs_str.isdigit() and int(epochs_str) > 0:
                epochs = int(epochs_str)
                break
            if key == K.KEY_ESC:
                return "menu"
            if key == K.KEY_CTRL_C:
                return None
            if key == K.KEY_BACKSPACE:
                epochs_str = epochs_str[:-1]
            elif key and key.isdigit():
                epochs_str += key

        bs_str = "32"
        while True:
            body = render_input("Batch size (--batch-size)", bs_str, hint="Training examples per gradient step. Larger = more stable updates but more GPU memory pressure on the Modal worker.  default 32")
            ctx.draw(title="Train model — batch size", body=body, footer="  [ENTER] next    [ESC] cancel")
            key = ctx.wait_key()
            if key == K.KEY_ENTER and bs_str.isdigit() and int(bs_str) > 0:
                batch_size = int(bs_str)
                break
            if key == K.KEY_ESC:
                return "menu"
            if key == K.KEY_CTRL_C:
                return None
            if key == K.KEY_BACKSPACE:
                bs_str = bs_str[:-1]
            elif key and key.isdigit():
                bs_str += key

    # Step 6: post-export ONNX quantization (applies to both fine-tune and skip-fine-tune).
    from ot_backend.semantic.train_options import (
        DEFAULT_TRAIN_QUANTIZATION,
        TRAIN_QUANTIZATION_INT8,
        TRAIN_QUANTIZATION_NONE,
        TRAIN_QUANTIZATION_OPTIONS,
    )

    quant_items: list[tuple[str, str]] = [
        (TRAIN_QUANTIZATION_NONE, "none — fp32 ONNX weights (default, larger runtime image)"),
        (TRAIN_QUANTIZATION_INT8, "int8 — dynamic int8 quantization (smaller weights, lower API RAM)"),
    ]
    quant_cursor = next(
        (i for i, (k, _) in enumerate(quant_items) if k == DEFAULT_TRAIN_QUANTIZATION),
        0,
    )
    while True:
        body = render_menu(quant_items, quant_cursor, prompt="ONNX quantization")
        ctx.draw(
            title="Train model — quantization",
            body=body,
            footer="  [↑/↓] move    [ENTER] select    [ESC] cancel",
        )
        key = ctx.wait_key()
        if key == K.KEY_UP:
            quant_cursor = (quant_cursor - 1) % len(quant_items)
        elif key == K.KEY_DOWN:
            quant_cursor = (quant_cursor + 1) % len(quant_items)
        elif key == K.KEY_ENTER:
            quantization = quant_items[quant_cursor][0]
            assert quantization in TRAIN_QUANTIZATION_OPTIONS
            break
        elif key == K.KEY_ESC:
            return "menu"
        elif key == K.KEY_CTRL_C:
            return None

    dataset_label = f"{dataset.slug}  ({str(dataset.id)[:8]})" if dataset is not None else "(synthesised on the fly — face texts only, augmentation=none)"
    summary_rows: list[tuple[str, str]] = [
        ("dataset", dataset_label),
        ("mode", "skip fine-tune (export as-is)" if skip else "fine-tune via Modal"),
        ("slug", slug),
        ("base model", base_spec.key),
    ]
    if not skip:
        summary_rows.append(("epochs", str(epochs)))
        summary_rows.append(("batch size", str(batch_size)))
    summary_rows.append(("quantization", quantization))
    body = render_confirm("Run train_model with these inputs?", summary_rows=summary_rows)
    ctx.draw(title="Train model — confirm", body=body, footer="  [Y] run    [N/ESC] cancel")
    while True:
        key = ctx.wait_key()
        if key == "y":
            break
        if key in ("n", K.KEY_ESC):
            return "menu"
        if key == K.KEY_CTRL_C:
            return None

    dataset_id = str(dataset.id) if dataset is not None else None
    return _run_with_logs(
        ctx,
        label=f"train {slug}",
        fn=lambda: _do_train_model(
            dataset_id=dataset_id,
            slug=slug,
            base_model_key=base_spec.key,
            epochs=epochs,
            batch_size=batch_size,
            skip_fine_tune=skip,
            quantization=quantization,
        ),
        next_screen="menu",
    )


def _do_train_model(
    *,
    dataset_id: str | None,
    slug: str,
    base_model_key: str,
    epochs: int,
    batch_size: int,
    skip_fine_tune: bool,
    quantization: str,
) -> str:
    from ot_backend.core.database import SessionLocal
    from ot_backend.semantic.base_model_catalog import get_semantic_base_model
    from ot_backend.semantic.bundle_registration import (
        register_model_bundle_bytes,
        semantic_model_artifact_keys,
    )

    lg = logging.getLogger("ot_backend.semantic.scripts.train_model")
    base = get_semantic_base_model(base_model_key)

    from ot_backend.semantic.train_options import validate_train_quantization

    quantization = validate_train_quantization(quantization)

    if skip_fine_tune:
        import importlib.util

        if importlib.util.find_spec("sentence_transformers") is None:
            raise RuntimeError(
                "Local skip-fine-tune needs the `semantic-train` extras "
                "(SentenceTransformer + onnx export). Install with:\n"
                "    uv sync --extra tui --extra semantic-train"
            )
        # No dataset, no encoding, no eval. Just package the base model.
        bundle_bytes = _skip_fine_tune_export_bundle(
            base_model=base.base_model,
            quantization=quantization,
        )
        augmentation_mode = "none"
        dataset_slug = None
        dataset_bytes: bytes | None = None
    else:
        from ot_backend.semantic.dataset_registry import get_semantic_dataset, get_semantic_dataset_bytes
        from ot_backend.semantic.eval_service import default_eval_queries_bytes

        if dataset_id is None:
            raise RuntimeError("Fine-tune requires a dataset_id.")
        with SessionLocal() as db:
            dataset = get_semantic_dataset(db, dataset_id)
            if dataset is None:
                raise KeyError(f"Dataset not found: {dataset_id}")
            augmentation_mode = dataset.augmentation_mode
            dataset_slug = dataset.slug
            dataset_bytes = get_semantic_dataset_bytes(db, dataset_id)
        eval_bytes = default_eval_queries_bytes()
        bundle_bytes = _run_modal_training(
            dataset_bytes,
            eval_bytes,
            base.base_model,
            epochs,
            batch_size,
            augmentation_mode,
            quantization,
        )

    config_json: dict[str, object] = {"base_model_key": base_model_key, "skip_fine_tune": skip_fine_tune}
    if dataset_slug is not None:
        config_json["dataset_slug"] = dataset_slug
    with SessionLocal() as db:
        model = register_model_bundle_bytes(
            db,
            slug=slug,
            base_model=base.base_model,
            embedding_dim=base.embedding_dim,
            artifact_bundle_bytes=bundle_bytes,
            dataset_id=dataset_id,
            dataset_bytes=dataset_bytes,
            source_semantic_data_version=None,
            augmentation_mode=augmentation_mode,
            config_json=config_json,
            metrics_json=None,
        )
        artifact_keys = semantic_model_artifact_keys(db, model.id)
    lg.info("Model registered. id=%s slug=%s", model.id, slug)
    return f"id={model.id}  artifacts: " + ", ".join(f"{k}={v}" for k, v in artifact_keys.items())


def _skip_fine_tune_export_bundle(*, base_model: str, quantization: str) -> bytes:
    """Build a model bundle: pytorch + onnx + precomputed face embeddings.

    No fine-tuning, no augmentation, no eval. We still encode every card face
    locally so the bundle ships with `embeddings/embeddings.npz` — promotion
    then uses the precomputed archive instead of re-encoding.
    """
    import io
    import shutil
    import tempfile
    import zipfile
    from datetime import UTC, datetime
    from pathlib import Path

    import numpy as np
    from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

    from ot_backend.core.database import SessionLocal
    from ot_backend.semantic.dataset_service import _face_text_records, _normalize_face_record
    from ot_backend.semantic.train_options import (
        TRAIN_QUANTIZATION_INT8,
        validate_train_quantization,
    )

    quantization_mode = validate_train_quantization(quantization)

    lg = logging.getLogger("ot_backend.semantic.scripts.train_model")

    lg.info("Loading card faces from DB.")
    with SessionLocal() as db:
        face_records = _face_text_records(db)
    oracle_ids = np.asarray([f.oracle_id for f in face_records])
    face_ixs = np.asarray([f.face_ix for f in face_records], dtype=np.int32)
    texts = [_normalize_face_record(f) for f in face_records]
    n_faces = len(texts)
    lg.info("Loaded %d card faces.", n_faces)

    lg.info("Loading base model: %s", base_model)
    model = SentenceTransformer(base_model)
    try:
        embedding_dim = int(model.get_sentence_embedding_dimension() or 0)
    except Exception:  # noqa: BLE001
        embedding_dim = 0

    encode_batch = 256
    lg.info("Encoding %d faces (batch=%d).", n_faces, encode_batch)
    parts: list[np.ndarray] = []
    for offset in range(0, n_faces, encode_batch):
        end = min(offset + encode_batch, n_faces)
        vectors = model.encode(
            texts[offset:end],
            batch_size=encode_batch,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        parts.append(np.asarray(vectors, dtype=np.float32))
        lg.info("Encoded %d / %d faces.", end, n_faces)
    embeddings = np.concatenate(parts, axis=0) if parts else np.zeros((0, embedding_dim), dtype=np.float32)
    if embedding_dim == 0 and embeddings.ndim == 2:
        embedding_dim = int(embeddings.shape[1])

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "bundle"
        root.mkdir()
        pytorch_dir = root / "models" / "pytorch"
        onnx_dir = root / "models" / "onnx"
        pytorch_dir.mkdir(parents=True)
        onnx_dir.mkdir(parents=True)

        lg.info("Saving PyTorch checkpoint.")
        model.save(str(pytorch_dir))

        lg.info("Exporting ONNX model.")
        onnx_model = SentenceTransformer(
            str(pytorch_dir),
            backend="onnx",
            model_kwargs={
                "provider": "CPUExecutionProvider",
                "export": True,
                "file_name": "onnx/model.onnx",
            },
            local_files_only=True,
        )
        onnx_model.save(str(onnx_dir))

        if quantization_mode == TRAIN_QUANTIZATION_INT8:
            from onnxruntime.quantization import QuantType, quantize_dynamic

            onnx_path = onnx_dir / "onnx" / "model.onnx"
            quantized_path = onnx_path.with_suffix(".quant.onnx")
            lg.info("Applying int8 dynamic quantization to %s", onnx_path)
            quantize_dynamic(
                model_input=str(onnx_path),
                model_output=str(quantized_path),
                weight_type=QuantType.QInt8,
            )
            original_size = onnx_path.stat().st_size
            quantized_size = quantized_path.stat().st_size
            shutil.move(str(quantized_path), str(onnx_path))
            lg.info(
                "ONNX int8 quantization done. %.1f MB -> %.1f MB (%.0f%%).",
                original_size / 1024 / 1024,
                quantized_size / 1024 / 1024,
                100 * quantized_size / original_size,
            )

        lg.info("Writing precomputed embeddings.npz.")
        embeddings_dir = root / "embeddings"
        embeddings_dir.mkdir()
        np.savez_compressed(
            embeddings_dir / "embeddings.npz",
            oracle_ids=oracle_ids,
            face_ixs=face_ixs,
            embeddings=embeddings,
        )

        now = datetime.now(UTC).isoformat()
        (root / "config.json").write_text(
            json.dumps(
                {
                    "base_model": base_model,
                    "skip_fine_tune": True,
                    "augmentation_mode": "none",
                    "embedding_dim": embedding_dim,
                    "quantization": quantization_mode,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (root / "metrics.json").write_text(
            json.dumps({"face_count": n_faces, "embedding_dim": embedding_dim, "skip_fine_tune": True}, indent=2),
            encoding="utf-8",
        )
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "generated_at": now,
                    "skip_fine_tune": True,
                    "embedding_source": "local-encode",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.rglob("*")):
                if path.is_dir():
                    continue
                archive.write(path, arcname=path.relative_to(root).as_posix())
        lg.info("Bundle assembled. faces=%d embedding_dim=%d", n_faces, embedding_dim)
        return buf.getvalue()


def _run_modal_training(
    dataset_bytes: bytes,
    eval_bytes: bytes,
    base_model: str,
    epochs: int,
    batch_size: int,
    augmentation_mode: str,
    quantization: str,
) -> bytes:
    from importlib import import_module

    from ot_backend.core.config import modal_client_configured, modal_environment_name

    if not modal_client_configured():
        raise RuntimeError("Modal credentials missing. Set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET.")
    modal_train = import_module("ot_backend.semantic.modal_train")
    with modal_train.app.run(environment_name=modal_environment_name()):
        return modal_train.train.remote(
            dataset_bytes,
            eval_bytes,
            base_model,
            epochs,
            batch_size,
            augmentation_mode,
            False,
            quantization,
        )


# ---------------------------------------------------------------------------
# Promote model wizard
# ---------------------------------------------------------------------------


def promote_screen(ctx: AppContext) -> str | None:
    from ot_backend.core.database import SessionLocal
    from ot_backend.semantic.model_registry import (
        SEMANTIC_MODEL_STATUS_ACTIVE,
        list_semantic_models,
    )

    try:
        with SessionLocal() as db:
            models = [m for m in list_semantic_models(db) if m.status != SEMANTIC_MODEL_STATUS_ACTIVE]
    except Exception as exc:  # noqa: BLE001
        return _error_screen(ctx, "Promote model", f"{type(exc).__name__}: {exc}")

    if not models:
        return _error_screen(ctx, "Promote model", "No promotable models. Train one first.")

    cursor = 0
    if ctx.preselected_model_id:
        for i, m in enumerate(models):
            if m.id == ctx.preselected_model_id:
                cursor = i
                break
        ctx.preselected_model_id = None
    while True:
        columns = ("Slug", "ID", "Status", "Base")
        rows = [(m.slug, str(m.id)[:8], m.status, str(m.base_model).split("/")[-1]) for m in models]
        body = render_row_table(columns=columns, rows=rows, cursor=cursor)
        ctx.draw(title="Promote model — step 1/3: pick model", body=body, footer="  [↑/↓] move    [ENTER] select    [ESC] cancel")
        key = ctx.wait_key()
        if key == K.KEY_UP:
            cursor = (cursor - 1) % len(models)
        elif key == K.KEY_DOWN:
            cursor = (cursor + 1) % len(models)
        elif key == K.KEY_ENTER:
            model = models[cursor]
            break
        elif key == K.KEY_ESC:
            return "menu"
        elif key == K.KEY_CTRL_C:
            return None

    ebs_str = "64"
    while True:
        body = render_input("Embed batch size (--embed-batch-size)", ebs_str, hint="Faces encoded per batch during embedding regeneration. Higher = fewer encoder calls but more GPU memory.  default 64")
        ctx.draw(title="Promote model — step 2/3: embed batch size", body=body, footer="  [ENTER] next    [ESC] cancel")
        key = ctx.wait_key()
        if key == K.KEY_ENTER and ebs_str.isdigit() and int(ebs_str) > 0:
            embed_batch_size = int(ebs_str)
            break
        if key == K.KEY_ESC:
            return "menu"
        if key == K.KEY_CTRL_C:
            return None
        if key == K.KEY_BACKSPACE:
            ebs_str = ebs_str[:-1]
        elif key and key.isdigit():
            ebs_str += key

    body = render_confirm(
        "Run promote_model with these inputs?",
        summary_rows=[
            ("model", f"{model.slug}  ({str(model.id)[:8]})"),
            ("embed batch size", str(embed_batch_size)),
        ],
    )
    ctx.draw(title="Promote model — step 3/3: confirm", body=body, footer="  [Y] run    [N/ESC] cancel")
    while True:
        key = ctx.wait_key()
        if key == "y":
            break
        if key in ("n", K.KEY_ESC):
            return "menu"
        if key == K.KEY_CTRL_C:
            return None

    def _do() -> str:
        from ot_backend.semantic.model_promotion import promote_semantic_model

        lg = logging.getLogger("ot_backend.semantic.scripts.promote_model")
        lg.info("Promoting model. id=%s embed_batch_size=%d", model.id, embed_batch_size)
        success = promote_semantic_model(model.id, embed_batch_size=embed_batch_size)
        if not success:
            raise RuntimeError(f"Promotion failed. id={model.id}")
        return f"id={model.id} status=active"

    return _run_with_logs(ctx, label=f"promote {model.slug}", fn=_do, next_screen="menu")


# ---------------------------------------------------------------------------
# Storage audit & sync
# ---------------------------------------------------------------------------


@dataclass
class _S3Object:
    key: str
    size: int


@dataclass
class _StorageAudit:
    bucket: str
    s3_datasets: dict[str, dict[str, _S3Object]]
    s3_models: dict[str, dict[str, _S3Object]]
    db_dataset_ids: set[str]
    db_model_ids: set[str]
    dataset_s3_only: set[str]
    dataset_db_only: set[str]
    model_s3_only: set[str]
    model_db_only: set[str]


def _audit_storage() -> _StorageAudit:
    """Walk S3 + DB and report drift."""
    from sqlalchemy import select

    from ot_backend.core.config import artifact_bucket_client, artifact_bucket_name
    from ot_backend.core.database import SessionLocal
    from ot_backend.core.models import SemanticDataset, SemanticModel

    client = artifact_bucket_client()
    bucket = artifact_bucket_name()

    s3_by_kind: dict[str, dict[str, dict[str, _S3Object]]] = {"datasets": {}, "models": {}}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix="semantic-registry/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            parts = key.split("/")
            if len(parts) != 4:
                continue
            _prefix, kind, uuid_part, filename = parts
            if kind not in s3_by_kind:
                continue
            s3_by_kind[kind].setdefault(uuid_part, {})[filename] = _S3Object(
                key=key, size=int(obj.get("Size", 0))
            )

    with SessionLocal() as db:
        db_dataset_ids = {row for row in db.scalars(select(SemanticDataset.id)).all()}
        db_model_ids = {row for row in db.scalars(select(SemanticModel.id)).all()}

    return _StorageAudit(
        bucket=bucket,
        s3_datasets=s3_by_kind["datasets"],
        s3_models=s3_by_kind["models"],
        db_dataset_ids=db_dataset_ids,
        db_model_ids=db_model_ids,
        dataset_s3_only=set(s3_by_kind["datasets"]) - db_dataset_ids,
        dataset_db_only=db_dataset_ids - set(s3_by_kind["datasets"]),
        model_s3_only=set(s3_by_kind["models"]) - db_model_ids,
        model_db_only=db_model_ids - set(s3_by_kind["models"]),
    )


_DATASET_FILENAME_TO_KIND = {
    "training-dataset.json": "dataset_json",
    "manifest.json": "manifest_json",
}
_MODEL_FILENAME_TO_KIND = {
    "bundle.zip": "bundle_zip",
    "training-dataset.json": "training_dataset",
    "eval.json": "eval_json",
    "manifest.json": "manifest_json",
}
_CONTENT_TYPE_BY_FILENAME = {
    "bundle.zip": "application/zip",
    "training-dataset.json": "application/json",
    "eval.json": "application/json",
    "manifest.json": "application/json",
}


class _ManifestMissingFieldsError(Exception):
    """Raised when an S3 manifest is missing fields needed for sync."""


def _load_manifest(object_key: str) -> dict[str, object]:
    from ot_backend.semantic.artifacts import download_artifact_bytes

    raw = download_artifact_bytes(object_key=object_key)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise _ManifestMissingFieldsError(f"Manifest at {object_key} is not a JSON object.")
    return payload


def _import_dataset_from_s3(dataset_id: str, files: dict[str, _S3Object]) -> bool:
    """Restore a SemanticDataset row using only manifest.json — no dataset.json download."""
    from datetime import UTC, datetime

    from ot_backend.core.database import SessionLocal
    from ot_backend.core.models import SemanticDataset, SemanticDatasetArtifact

    lg = logging.getLogger("ot_backend.tui.storage")

    if "manifest.json" not in files:
        lg.warning("Dataset %s has no manifest.json in S3 — run the backfill first.", dataset_id)
        return False

    try:
        manifest = _load_manifest(files["manifest.json"].key)
    except (json.JSONDecodeError, _ManifestMissingFieldsError) as exc:
        lg.warning("Dataset %s manifest unreadable (%s) — run the backfill.", dataset_id, exc)
        return False

    augmentation_mode = str(manifest.get("augmentation_mode") or "none")
    source_version: int | None = None
    v = manifest.get("source_semantic_data_version")
    if isinstance(v, int):
        source_version = v
    elif isinstance(v, str) and v.isdigit():
        source_version = int(v)

    metrics_json = manifest.get("dataset_metrics") if isinstance(manifest.get("dataset_metrics"), dict) else None

    now = datetime.now(UTC).replace(tzinfo=None)
    base_slug = f"restored-{dataset_id[:8]}"
    slug = base_slug

    with SessionLocal() as db:
        suffix = 0
        from ot_backend.core.models import SemanticDataset as _SD

        while db.query(_SD).filter(_SD.slug == slug).first() is not None:
            suffix += 1
            slug = f"{base_slug}-{suffix}"

        dataset = SemanticDataset(
            id=dataset_id,
            slug=slug,
            status="ready",
            augmentation_mode=augmentation_mode,
            source_semantic_data_version=source_version,
            config_json=None,
            metrics_json=metrics_json,
            created_at=now,
        )
        db.add(dataset)
        db.flush()

        for filename, kind in _DATASET_FILENAME_TO_KIND.items():
            entry = files.get(filename)
            if entry is None:
                continue
            db.add(
                SemanticDatasetArtifact(
                    dataset_id=dataset_id,
                    artifact_kind=kind,
                    object_key=entry.key,
                    sha256=None,
                    size_bytes=entry.size,
                    content_type=_CONTENT_TYPE_BY_FILENAME.get(filename, "application/octet-stream"),
                    metadata_json=None,
                    created_at=now,
                )
            )
        db.commit()
    lg.info("Imported dataset id=%s slug=%s", dataset_id, slug)
    return True


def _import_model_from_s3(model_id: str, files: dict[str, _S3Object]) -> bool:
    """Restore a SemanticModel row using only manifest.json — no bundle download."""
    from datetime import UTC, datetime

    from ot_backend.core.database import SessionLocal
    from ot_backend.core.models import SemanticModel, SemanticModelArtifact

    lg = logging.getLogger("ot_backend.tui.storage")

    if "manifest.json" not in files:
        lg.warning("Model %s has no manifest.json in S3 — run the backfill first.", model_id)
        return False

    try:
        manifest = _load_manifest(files["manifest.json"].key)
    except (json.JSONDecodeError, _ManifestMissingFieldsError) as exc:
        lg.warning("Model %s manifest unreadable (%s) — run the backfill.", model_id, exc)
        return False

    base_model = manifest.get("base_model")
    embedding_dim = manifest.get("embedding_dim")
    if not isinstance(base_model, str) or not isinstance(embedding_dim, int):
        lg.warning(
            "Model %s manifest is missing base_model/embedding_dim — run the backfill.",
            model_id,
        )
        return False

    raw_config = manifest.get("config")
    config: dict[str, object] = {str(k): v for k, v in raw_config.items()} if isinstance(raw_config, dict) else {}
    metrics = manifest.get("metrics") if isinstance(manifest.get("metrics"), dict) else None

    # Mirror what bundle_registration does at upload time: keep the source
    # semantic_data_version inside config_json so the promotion staleness check
    # (model_promotion._get_model_source_data_version) can find it.
    source_version = manifest.get("source_semantic_data_version")
    if isinstance(source_version, int):
        config["semantic_data_version"] = source_version
    elif isinstance(source_version, str) and source_version.isdigit():
        config["semantic_data_version"] = int(source_version)
    dataset_metadata = manifest.get("dataset_metadata")
    if isinstance(dataset_metadata, dict) and dataset_metadata:
        config["dataset_metadata"] = dataset_metadata

    now = datetime.now(UTC).replace(tzinfo=None)
    base_slug = f"restored-{model_id[:8]}"
    slug = base_slug

    with SessionLocal() as db:
        suffix = 0
        from ot_backend.core.models import SemanticModel as _SM

        while db.query(_SM).filter(_SM.slug == slug).first() is not None:
            suffix += 1
            slug = f"{base_slug}-{suffix}"

        model = SemanticModel(
            id=model_id,
            slug=slug,
            base_model=base_model,
            status="uploaded",
            is_active=False,
            embedding_dim=embedding_dim,
            dataset_id=None,
            config_json=config,
            metrics_json=metrics,
            error_message=None,
            created_at=now,
            activated_at=None,
        )
        db.add(model)
        db.flush()

        for filename, kind in _MODEL_FILENAME_TO_KIND.items():
            entry = files.get(filename)
            if entry is None:
                continue
            db.add(
                SemanticModelArtifact(
                    model_id=model_id,
                    artifact_kind=kind,
                    object_key=entry.key,
                    sha256=None,
                    size_bytes=entry.size,
                    content_type=_CONTENT_TYPE_BY_FILENAME.get(filename, "application/octet-stream"),
                    metadata_json=None,
                    created_at=now,
                )
            )
        db.commit()
    lg.info("Imported model id=%s slug=%s base_model=%s", model_id, slug, base_model)
    return True


def _render_audit_body(audit: _StorageAudit):
    from rich.console import Group
    from rich.text import Text

    rows: list[tuple[str, str, str, str]] = []
    rows.append((
        "",
        "Datasets",
        f"DB:{len(audit.db_dataset_ids)}  S3:{len(audit.s3_datasets)}",
        f"orphan→ S3:{len(audit.dataset_s3_only)} DB:{len(audit.dataset_db_only)}",
    ))
    rows.append((
        "",
        "Models",
        f"DB:{len(audit.db_model_ids)}  S3:{len(audit.s3_models)}",
        f"orphan→ S3:{len(audit.model_s3_only)} DB:{len(audit.model_db_only)}",
    ))
    table = render_kv_table(rows)

    detail_parts: list[Text] = []
    if audit.dataset_s3_only:
        detail_parts.append(Text(f"\nS3-only datasets ({len(audit.dataset_s3_only)}) — will be imported on sync:", style="bold yellow"))
        for did in sorted(audit.dataset_s3_only):
            detail_parts.append(Text(f"  {did}", style="yellow"))
    if audit.model_s3_only:
        detail_parts.append(Text(f"\nS3-only models ({len(audit.model_s3_only)}) — will be imported on sync:", style="bold yellow"))
        for mid in sorted(audit.model_s3_only):
            detail_parts.append(Text(f"  {mid}", style="yellow"))
    if audit.dataset_db_only:
        detail_parts.append(Text(f"\nDB-only datasets ({len(audit.dataset_db_only)}) — DB rows missing in S3:", style="bold red"))
        for did in sorted(audit.dataset_db_only):
            detail_parts.append(Text(f"  {did}", style="red"))
    if audit.model_db_only:
        detail_parts.append(Text(f"\nDB-only models ({len(audit.model_db_only)}) — DB rows missing in S3:", style="bold red"))
        for mid in sorted(audit.model_db_only):
            detail_parts.append(Text(f"  {mid}", style="red"))
    if not (audit.dataset_s3_only or audit.model_s3_only or audit.dataset_db_only or audit.model_db_only):
        detail_parts.append(Text("\n✓ S3 and DB are in sync.", style="bold green"))

    return Group(Text(f"bucket: {audit.bucket}", style="dim"), Text(""), table, *detail_parts)


def storage_screen(ctx: AppContext) -> str | None:
    from rich.console import Group
    from rich.text import Text

    ctx.draw(title="Storage", body=Text("Scanning S3 + DB…", style="dim"), footer="  please wait…")
    try:
        audit = _audit_storage()
    except Exception as exc:  # noqa: BLE001
        return _error_screen(ctx, "Storage", f"Audit failed: {type(exc).__name__}: {exc}")

    while True:
        body = _render_audit_body(audit)
        s3_only_total = len(audit.dataset_s3_only) + len(audit.model_s3_only)
        footer = f"  [S] sync {s3_only_total} S3-only → DB    [B] backfill manifests    [R] re-audit    [ESC] back"
        ctx.draw(title="Storage audit", body=body, footer=footer)
        key = ctx.wait_key()
        if key == K.KEY_ESC:
            return "menu"
        if key == K.KEY_CTRL_C:
            return None
        if key == "r":
            try:
                audit = _audit_storage()
            except Exception as exc:  # noqa: BLE001
                ctx.draw(title="Storage", body=Group(Text(f"Audit failed: {type(exc).__name__}: {exc}", style="red")), footer="  [ESC] back")
                if ctx.wait_key() == K.KEY_ESC:
                    return "menu"
        elif key == "b":
            def _do_backfill() -> str:
                from ot_backend.semantic.manifest_backfill import backfill_manifests

                report = backfill_manifests()
                return (
                    f"models scanned={report.models_scanned} upgraded={report.models_upgraded} "
                    f"skipped={report.models_skipped} failed={len(report.models_failed)}    "
                    f"datasets scanned={report.datasets_scanned} upgraded={report.datasets_upgraded} "
                    f"skipped={report.datasets_skipped} failed={len(report.datasets_failed)}"
                )

            result = _run_with_logs(ctx, label="backfill manifests", fn=_do_backfill, next_screen="storage")
            return result
        elif key == "s":
            if s3_only_total == 0:
                continue
            ds_s3_only = list(audit.dataset_s3_only)
            md_s3_only = list(audit.model_s3_only)
            s3_datasets = audit.s3_datasets
            s3_models = audit.s3_models

            def _do_sync() -> str:
                lg = logging.getLogger("ot_backend.tui.storage")
                imported_d = 0
                imported_m = 0
                for did in sorted(ds_s3_only):
                    try:
                        if _import_dataset_from_s3(did, s3_datasets[did]):
                            imported_d += 1
                    except Exception as exc:  # noqa: BLE001
                        lg.error("Dataset %s import failed: %s", did, exc)
                for mid in sorted(md_s3_only):
                    try:
                        if _import_model_from_s3(mid, s3_models[mid]):
                            imported_m += 1
                    except Exception as exc:  # noqa: BLE001
                        lg.error("Model %s import failed: %s", mid, exc)
                return f"imported datasets={imported_d}  models={imported_m}"

            result = _run_with_logs(ctx, label="sync S3 → DB", fn=_do_sync, next_screen="storage")
            return result


# ---------------------------------------------------------------------------
# Run with streaming logs
# ---------------------------------------------------------------------------


# Attach to the root namespace ONLY. Every `ot_backend.*` logger propagates up
# to here, so we capture each record exactly once. Attaching at every level
# multiplied output by the depth of the emitter.
_STREAMED_LOGGER_NAMES = ("ot_backend",)


class _DequeLogHandler(logging.Handler):
    def __init__(self, sink: "deque[str]") -> None:
        super().__init__(level=logging.INFO)
        self.sink = sink
        self.setFormatter(logging.Formatter("%(asctime)s  %(name)s  %(levelname)s  %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.sink.append(self.format(record))
        except Exception:
            pass


def _run_with_logs(ctx: AppContext, *, label: str, fn: Callable[[], str | None], next_screen: str) -> str | None:
    sink: "deque[str]" = deque(maxlen=2000)
    handler = _DequeLogHandler(sink)
    attached: list[tuple[logging.Logger, int, bool]] = []
    for name in _STREAMED_LOGGER_NAMES:
        lg = logging.getLogger(name)
        attached.append((lg, lg.level, lg.propagate))
        if lg.level == logging.NOTSET or lg.level > logging.INFO:
            lg.setLevel(logging.INFO)
        lg.addHandler(handler)

    sink.append(f"▶ Starting: {label}")
    result: dict[str, object] = {}

    def worker() -> None:
        try:
            result["summary"] = fn()
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"
            import traceback

            for line in traceback.format_exc().splitlines():
                sink.append(line)

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    spinner_i = 0
    try:
        while t.is_alive():
            spinner_i += 1
            title = f"{_SPINNER_FRAMES[spinner_i % len(_SPINNER_FRAMES)]} running: {label}"
            body = render_logs(list(sink), max_lines=_log_panel_height(ctx))
            ctx.draw(title=title, body=body, footer="  streaming…  Ctrl-C to cancel app (does not stop the worker)")
            time.sleep(0.08)
        t.join(timeout=1.0)
        if "error" in result:
            title = f"✗ failed: {label}"
            summary = f"[red]{result['error']}[/]"
        else:
            title = f"✓ done: {label}"
            summary = f"[green]{result.get('summary') or 'completed'}[/]"
        while True:
            body = render_logs(list(sink), summary=summary, max_lines=_log_panel_height(ctx))
            ctx.draw(title=title, body=body, footer="  [ENTER] back to menu")
            key = ctx.wait_key()
            if key == K.KEY_ENTER:
                break
            if key == K.KEY_CTRL_C:
                return None
    finally:
        for lg, level, propagate in attached:
            try:
                lg.removeHandler(handler)
            except ValueError:
                pass
            lg.setLevel(level)
            lg.propagate = propagate

    return next_screen


def _log_panel_height(ctx: AppContext) -> int:
    # Available rows inside the body panel ≈ console height − header(1) − footer(1) − outer panel borders(2) − body padding(2) − summary(2)
    return max(5, ctx.live.console.size.height - 10)


# ---------------------------------------------------------------------------
# Error screen
# ---------------------------------------------------------------------------


def _error_screen(ctx: AppContext, title: str, message: str) -> str | None:
    from rich.console import Group
    from rich.text import Text

    body = Group(Text(""), Text(message, style="red"), Text(""), Text("[ENTER] back to menu", style="dim"))
    ctx.draw(title=title, body=body, footer="  [ENTER] back to menu    [Q] quit")
    while True:
        key = ctx.wait_key()
        if key == K.KEY_ENTER:
            return "menu"
        if key == "q" or key == K.KEY_CTRL_C:
            return None


# ---------------------------------------------------------------------------
# Screen dispatch
# ---------------------------------------------------------------------------


def _load_admin_ip_state() -> list[dict[str, object]]:
    from ot_backend.core.database import SessionLocal
    from ot_backend.core.models import AdminIpState

    with SessionLocal() as db:
        rows = db.query(AdminIpState).order_by(AdminIpState.banned.desc(), AdminIpState.last_failure_at.desc()).all()
        return [
            {
                "ip_address": r.ip_address,
                "failures": r.failures,
                "locked_until": r.locked_until.isoformat() if r.locked_until else None,
                "banned": r.banned,
                "banned_at": r.banned_at.isoformat() if r.banned_at else None,
                "banned_reason": r.banned_reason or "",
                "last_failure_at": r.last_failure_at.isoformat() if r.last_failure_at else None,
            }
            for r in rows
        ]


def _ban_admin_ip(ip_address: str, reason: str) -> None:
    from datetime import UTC, datetime

    from ot_backend.core.database import SessionLocal
    from ot_backend.core.models import AdminIpState

    now = datetime.now(UTC).replace(tzinfo=None)
    with SessionLocal() as db:
        state = db.get(AdminIpState, ip_address)
        if state is None:
            state = AdminIpState(ip_address=ip_address, failures=0, last_failure_at=now)
            db.add(state)
        state.banned = True
        state.banned_at = now
        state.banned_reason = reason or None
        db.commit()


def _unban_admin_ip(ip_address: str) -> None:
    from ot_backend.core.database import SessionLocal
    from ot_backend.core.models import AdminIpState

    with SessionLocal() as db:
        state = db.get(AdminIpState, ip_address)
        if state is None:
            return
        state.banned = False
        state.banned_at = None
        state.banned_reason = None
        db.commit()


def _delete_admin_ip(ip_address: str) -> None:
    from ot_backend.core.database import SessionLocal
    from ot_backend.core.models import AdminIpState

    with SessionLocal() as db:
        state = db.get(AdminIpState, ip_address)
        if state is None:
            return
        db.delete(state)
        db.commit()


def admin_ips_screen(ctx: AppContext) -> str | None:
    try:
        rows = _load_admin_ip_state()
    except Exception as exc:  # noqa: BLE001
        return _error_screen(ctx, "Admin IP bans", f"{type(exc).__name__}: {exc}")

    cursor = 0
    while True:
        columns = ("IP", "Fails", "Banned", "Reason", "Locked until", "Last failure")
        display_rows = [
            (
                str(r["ip_address"]),
                str(r["failures"]),
                "yes" if r["banned"] else "no",
                str(r["banned_reason"] or "")[:32],
                (str(r["locked_until"]) or "—")[:19],
                (str(r["last_failure_at"]) or "—")[:19],
            )
            for r in rows
        ]
        body = render_row_table(
            columns=columns,
            rows=display_rows,
            cursor=cursor if rows else 0,
            empty_message="No admin IP state recorded.",
        )
        footer = "  [↑/↓] move    [A] add+ban    [B] ban    [U] unban    [D] delete row    [R] reload    [ESC] menu"
        ctx.draw(title="Admin IP bans", body=body, footer=footer)
        key = ctx.wait_key()

        if key == K.KEY_ESC:
            return "menu"
        if key == K.KEY_CTRL_C or key == "q":
            return None
        if key == "r":
            try:
                rows = _load_admin_ip_state()
            except Exception as exc:  # noqa: BLE001
                return _error_screen(ctx, "Admin IP bans", f"{type(exc).__name__}: {exc}")
            cursor = min(cursor, max(0, len(rows) - 1))
            continue
        if rows and key == K.KEY_UP:
            cursor = (cursor - 1) % len(rows)
            continue
        if rows and key == K.KEY_DOWN:
            cursor = (cursor + 1) % len(rows)
            continue
        if key == "a":
            ip_res = _prompt_text(
                ctx,
                title="Admin IP bans — add",
                label="IP address",
                hint="exact match against X-Real-IP (or X-Forwarded-For first hop).",
            )
            if ip_res is None or ip_res[1] is not None or not ip_res[0].strip():
                continue
            reason_res = _prompt_text(
                ctx,
                title="Admin IP bans — add",
                label="Reason (optional)",
                allow_empty=True,
            )
            if reason_res is None:
                continue
            try:
                _ban_admin_ip(ip_res[0].strip(), reason_res[0].strip() if reason_res[1] is None else "")
                rows = _load_admin_ip_state()
            except Exception as exc:  # noqa: BLE001
                return _error_screen(ctx, "Admin IP bans", f"{type(exc).__name__}: {exc}")
            cursor = 0
            continue
        if not rows:
            continue
        selected_ip = str(rows[cursor]["ip_address"])
        if key == "b":
            reason_res = _prompt_text(
                ctx,
                title=f"Ban {selected_ip}",
                label="Reason (optional)",
                allow_empty=True,
            )
            if reason_res is None:
                continue
            try:
                _ban_admin_ip(selected_ip, reason_res[0].strip() if reason_res[1] is None else "")
                rows = _load_admin_ip_state()
            except Exception as exc:  # noqa: BLE001
                return _error_screen(ctx, "Admin IP bans", f"{type(exc).__name__}: {exc}")
            continue
        if key == "u":
            try:
                _unban_admin_ip(selected_ip)
                rows = _load_admin_ip_state()
            except Exception as exc:  # noqa: BLE001
                return _error_screen(ctx, "Admin IP bans", f"{type(exc).__name__}: {exc}")
            continue
        if key == "d":
            try:
                _delete_admin_ip(selected_ip)
                rows = _load_admin_ip_state()
            except Exception as exc:  # noqa: BLE001
                return _error_screen(ctx, "Admin IP bans", f"{type(exc).__name__}: {exc}")
            cursor = min(cursor, max(0, len(rows) - 1))
            continue


_SCREENS: dict[str, Callable[[AppContext], "str | None"]] = {
    "boot": boot_screen,
    "menu": menu_screen,
    "datasets": datasets_screen,
    "models": models_screen,
    "build": build_screen,
    "train": train_screen,
    "promote": promote_screen,
    "storage": storage_screen,
    "admin_ips": admin_ips_screen,
}


if __name__ == "__main__":
    raise SystemExit(main())
