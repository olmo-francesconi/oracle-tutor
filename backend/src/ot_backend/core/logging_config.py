from __future__ import annotations

import logging
import os
import sys
import time
from functools import wraps
from typing import Callable, ParamSpec, TypeVar

from .config import DATA_DIR, is_production_env

P = ParamSpec("P")
R = TypeVar("R")
_loggers_configured = False


# ---------------------------------------------------------------------------
# Handler / formatter factories
# ---------------------------------------------------------------------------


def _formatter() -> logging.Formatter:
    return logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def _console_handler() -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_formatter())
    return handler


def _file_handler(filename: str) -> logging.Handler:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(DATA_DIR / filename)
    handler.setFormatter(_formatter())
    return handler


def _log_to_files() -> bool:
    """
    Default to stdout-only in production (Railway-friendly).
    Set OT_LOG_TO_FILES=true to also write /app/data/*.log.
    """
    explicit = os.getenv("OT_LOG_TO_FILES")
    if explicit is not None:
        return explicit.lower() in ("1", "true", "yes")
    return not is_production_env()


# ---------------------------------------------------------------------------
# Logger setup
# ---------------------------------------------------------------------------


def setup_loggers() -> None:
    """Configure a small set of named loggers used across API, ingest, and semantic flows."""
    global _loggers_configured
    if _loggers_configured:
        return

    console = _console_handler()
    write_files = _log_to_files()
    api_file = _file_handler("api.log") if write_files else None
    update_file = _file_handler("update.log") if write_files else None
    semantic_file = _file_handler("semantic.log") if write_files else None

    def configure(name: str, level: int, file_handler: logging.Handler | None) -> None:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.propagate = False
        if file_handler is not None:
            logger.addHandler(file_handler)
        logger.addHandler(console)

    configure("ot_backend.api", logging.INFO, api_file)
    configure("ot_backend.db", logging.INFO, api_file)
    configure("ot_backend.data", logging.INFO, update_file)
    configure("ot_backend.ingest", logging.INFO, update_file)
    configure("ot_backend.semantic", logging.INFO, semantic_file)
    configure("ot_backend.semantic.train", logging.INFO, semantic_file)
    configure("ot_backend.semantic.compute", logging.INFO, semantic_file)
    configure("ot_backend.semantic.index", logging.INFO, semantic_file)
    _loggers_configured = True


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------


def log_performance(
    func: Callable[P, R] | None = None,
    *,
    logger: logging.Logger | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]] | Callable[P, R]:
    """Decorator to time endpoint handlers (sync functions)."""

    def decorator(f: Callable[P, R]) -> Callable[P, R]:
        @wraps(f)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            current_logger = logger or logging.getLogger()
            start = time.perf_counter()
            result = f(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - start) * 1000

            query = kwargs.get("q") or kwargs.get("oracle_id") or kwargs.get("card_id") or ""
            limit = kwargs.get("limit")
            result_count = 1
            if isinstance(result, (list, tuple)):
                result_count = len(result)
            else:
                items = getattr(result, "items", None)
                if isinstance(items, (list, tuple)):
                    result_count = len(items)

            parts = [f"Found {result_count} matches in {elapsed_ms:.2f} ms"]
            if query:
                parts.append(f"query: '{query}'")
            if limit is not None:
                parts.append(f"limit: {limit}")
            current_logger.info(", ".join(parts))
            return result

        return wrapper

    if func is not None and callable(func):
        return decorator(func)
    return decorator
