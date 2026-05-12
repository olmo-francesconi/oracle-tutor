from __future__ import annotations

import argparse
import os
from pathlib import Path

# backend/ is one level up from this file (backend/scripts/_common.py → backend/).
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def add_prod_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--prod",
        action="store_true",
        default=False,
        help="Load backend/.env.prod instead of backend/.env (production env vars).",
    )


def _load_env_file(env_file: Path) -> None:
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


def load_env(*, prod: bool) -> None:
    """Load env vars from backend/.env.prod (--prod) or backend/.env (default)."""
    name = ".env.prod" if prod else ".env"
    _load_env_file(_BACKEND_ROOT / name)


def setup_logging() -> None:
    from ot_backend.core.logging_config import setup_loggers
    setup_loggers()


def get_session():
    """Return the SessionLocal context manager from core.database."""
    from ot_backend.core.database import SessionLocal
    return SessionLocal
