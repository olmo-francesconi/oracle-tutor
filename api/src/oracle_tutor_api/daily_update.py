#!/usr/bin/env python3
"""
Daily update script for MTG card database.

This script checks for updates from Scryfall and rebuilds the local data files
if new data is available. It can be run manually or scheduled via cron.
"""

import sys
import logging

from .data_builder import update_scryfall_data, ensure_data_dir
from .config import DATA_DIR
from .logging_config import setup_loggers

logger = logging.getLogger("oracle_tutor_api.update")

def main() -> int:
    """
    Check for updates and rebuild data if needed.
    
    Returns:
        0 if successful, 1 if an error occurred
    """
    setup_loggers()
    ensure_data_dir()  # Make sure data directory exists
    
    try:
        logger.info("Starting daily update check...")
        updated = update_scryfall_data(force=False)
        
        if updated:
            logger.info("Database updated successfully. New data downloaded and indexed.")
        else:
            logger.info("Database is already up to date. No update needed.")
        
        return 0
    except Exception as e:
        logger.error(f"Error during update: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
