import logging
import sys
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
    
    update_logger = logging.getLogger("mtg_search.update")
    update_logger.setLevel(logging.INFO)
    update_logger.propagate = False
    
    # Clear existing handlers to avoid duplicates on reload/re-import
    if update_logger.handlers:
        update_logger.handlers.clear()
        
    update_logger.addHandler(update_handler)
    update_logger.addHandler(console_handler)

    # --- Data Logger ---
    # Used by data_builder.py
    data_logger = logging.getLogger("mtg_search.data")
    data_logger.setLevel(logging.INFO)
    data_logger.propagate = False
    
    if data_logger.handlers:
        data_logger.handlers.clear()

    data_logger.addHandler(update_handler) # Data operations log to update.log
    data_logger.addHandler(console_handler)

    # --- API Logger ---
    # Used by api.py
    api_handler = get_file_handler("api.log")
    
    api_logger = logging.getLogger("mtg_search.api")
    api_logger.setLevel(logging.INFO)
    api_logger.propagate = False
    
    if api_logger.handlers:
        api_logger.handlers.clear()
        
    api_logger.addHandler(api_handler)
    api_logger.addHandler(console_handler)

