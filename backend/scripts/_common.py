from __future__ import annotations

import argparse
import os
from pathlib import Path

# Repo root is three levels up from this file (backend/scripts/_common.py → backend/ → repo root).
_REPO_ROOT = Path(__file__).resolve().parents[2]


def add_prod_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--prod",
        action="store_true",
        default=False,
        help="Load .env.prod from repo root before connecting (implies production env vars).",
    )


def load_env(*, prod: bool) -> None:
    """Load environment variables from .env.prod (if --prod) or do nothing."""
    if not prod:
        return
    env_file = _REPO_ROOT / ".env.prod"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore[import]
        load_dotenv(env_file, override=False)
        return
    except ImportError:
        pass
    # Fallback: parse manually — key=value, skip comments and blank lines.
    for line in env_file.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def setup_logging() -> None:
    from ot_backend.core.logging_config import setup_loggers
    setup_loggers()


def get_session():
    """Return the SessionLocal context manager from core.database."""
    from ot_backend.core.database import SessionLocal
    return SessionLocal
