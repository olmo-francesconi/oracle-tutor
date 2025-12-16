from __future__ import annotations

import logging
import sys
import time
from functools import wraps
from typing import Callable

from .config import DATA_DIR


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


def setup_loggers() -> None:
    """Configure a small set of named loggers used across api/worker/ingestion."""
    console = _console_handler()
    api_file = _file_handler("api.log")
    update_file = _file_handler("update.log")

    def configure(name: str, level: int, file_handler: logging.Handler) -> None:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.propagate = False
        if logger.handlers:
            logger.handlers.clear()
        logger.addHandler(file_handler)
        logger.addHandler(console)

    configure("oracle_tutor_api.api", logging.INFO, api_file)
    configure("oracle_tutor_api.data", logging.INFO, update_file)
    configure("oracle_tutor_api.worker", logging.INFO, update_file)


def log_performance(func: Callable | None = None, *, logger: logging.Logger | None = None) -> Callable:
    """Decorator to time endpoint handlers (sync functions)."""

    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def wrapper(*args, **kwargs):
            current_logger = logger or logging.getLogger()
            start = time.perf_counter()
            result = f(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - start) * 1000

            query = kwargs.get("q") or kwargs.get("card_id") or (args[0] if args else "")
            limit = kwargs.get("limit") or (args[1] if len(args) > 1 else None)
            result_count = len(result) if isinstance(result, (list, tuple)) else 1

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


