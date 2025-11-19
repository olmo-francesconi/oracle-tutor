#!/usr/bin/env python3
"""
Scheduler for daily MTG card database updates.

This script runs a background scheduler that checks for updates from Scryfall
daily and rebuilds the local data files if new data is available.

Usage:
    python -m mtg_search.scheduler

The scheduler will check for updates once per day at the configured time
(default: 2:00 AM local time).
"""

import argparse
import logging
import signal
import sys
from datetime import time

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .daily_update import main as update_main
from .data_builder import ensure_data_dir
from .config import DATA_DIR

log_file = DATA_DIR / 'scheduler.log'
ensure_data_dir()  # Make sure data directory exists
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

scheduler = BlockingScheduler()


def run_update():
    """Wrapper function to run the update and handle errors."""
    try:
        exit_code = update_main()
        if exit_code == 0:
            logger.info("Scheduled update completed successfully")
        else:
            logger.warning(f"Scheduled update completed with exit code {exit_code}")
    except Exception as e:
        logger.error(f"Error in scheduled update: {e}", exc_info=True)


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info("Received shutdown signal, stopping scheduler...")
    scheduler.shutdown()
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="Run a scheduler for daily MTG card database updates."
    )
    parser.add_argument(
        "--hour",
        type=int,
        default=2,
        help="Hour of day to run update (0-23, default: 2)",
    )
    parser.add_argument(
        "--minute",
        type=int,
        default=0,
        help="Minute of hour to run update (0-59, default: 0)",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run update once immediately and exit (for testing)",
    )
    args = parser.parse_args()

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.run_once:
        logger.info("Running update once (--run-once mode)...")
        run_update()
        return

    # Schedule daily update
    update_time = time(hour=args.hour, minute=args.minute)
    scheduler.add_job(
        run_update,
        trigger=CronTrigger(hour=args.hour, minute=args.minute),
        id="daily_update",
        name="Daily Scryfall database update",
        replace_existing=True,
    )

    logger.info(
        f"Scheduler started. Daily updates will run at {update_time.strftime('%H:%M')} local time."
    )
    logger.info("Press Ctrl+C to stop the scheduler.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()

