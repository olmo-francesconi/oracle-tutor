from functools import wraps
import logging
import sys
import time
from typing import Callable
from .config import DATA_DIR

def get_formatter():
    return logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def get_console_handler():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(get_formatter())
    return handler

def get_file_handler(filename):
    log_file = DATA_DIR / filename
    handler = logging.FileHandler(log_file)
    handler.setFormatter(get_formatter())
    return handler

def setup_loggers():
    """
    Configure loggers for the application.
    """
    # Ensure data directory exists for log files
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    console_handler = get_console_handler()
    
    # --- Update Logger ---
    # Used by daily_update.py
    update_handler = get_file_handler("update.log")
    
    update_logger = logging.getLogger("manaseek_api.update")
    update_logger.setLevel(logging.INFO)
    update_logger.propagate = False
    
    # Clear existing handlers to avoid duplicates on reload/re-import
    if update_logger.handlers:
        update_logger.handlers.clear()
        
    update_logger.addHandler(update_handler)
    update_logger.addHandler(console_handler)

    # --- Data Logger ---
    # Used by data_builder.py
    data_logger = logging.getLogger("manaseek_api.data")
    data_logger.setLevel(logging.INFO)
    data_logger.propagate = False
    
    if data_logger.handlers:
        data_logger.handlers.clear()

    data_logger.addHandler(update_handler) # Data operations log to update.log
    data_logger.addHandler(console_handler)

    # --- API Logger ---
    # Used by api.py
    api_handler = get_file_handler("api.log")
    
    api_logger = logging.getLogger("manaseek_api.api")
    api_logger.setLevel(logging.INFO)
    api_logger.propagate = False
    
    if api_logger.handlers:
        api_logger.handlers.clear()
        
    api_logger.addHandler(api_handler)
    api_logger.addHandler(console_handler)


def log_performance(func: Callable = None, *, logger: logging.Logger = None) -> Callable:
    """
    Decorator to log the performance of API endpoint calls.
    Times the entire function execution and logs the results.

    Usage:
        @log_performance(logger=my_logger)
        def my_func(...): ...

    If logger is not specified, will use the root logger.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            current_logger = logger or logging.getLogger()
            start_time = time.perf_counter()
            result = f(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Extract query parameters for logging context (flexible for different endpoints)
            query = kwargs.get('q') or kwargs.get('card_id') or (args[0] if args else '')
            limit = kwargs.get('limit') or (args[1] if len(args) > 1 else None)

            # Get result count
            result_count = len(result) if isinstance(result, (list, tuple)) else 1

            # Build log message
            log_parts = [f"Found {result_count} matches in {elapsed_ms:.2f} ms"]
            if query:
                log_parts.append(f"query: '{query}'")
            if limit is not None:
                log_parts.append(f"limit: {limit}")

            current_logger.info(", ".join(log_parts))

            return result
        return wrapper

    if func is not None and callable(func):
        return decorator(func)
    return decorator