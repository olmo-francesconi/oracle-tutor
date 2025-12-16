from __future__ import annotations

import logging
import os
import signal
import sys
import time
from threading import Event

from .data_builder import update_scryfall_data
from .logging_config import setup_loggers

setup_loggers()
logger = logging.getLogger("oracle_tutor_api.worker")

stop_event = Event()


def _signal_handler(signum, frame):
    logger.info("Signal %s received. Shutting down worker...", signum)
    stop_event.set()


def main() -> int:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info("Oracle Tutor Worker starting...")

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except Exception:
        logger.exception("APScheduler not installed. Worker cannot run schedules.")
        return 1

    def run_update():
        try:
            logger.info("Running scheduled database update...")
            updated = update_scryfall_data(force=False)
            logger.info("Update finished (updated=%s).", updated)
        except Exception:
            logger.exception("Error in scheduled update")

    update_hour = int(os.getenv("ORACLE_TUTOR_API_UPDATE_HOUR", "2"))

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_update,
        trigger=CronTrigger(hour=update_hour, minute=0),
        id="daily_update",
        name="Daily Scryfall database update",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started (Daily at %d:00).", update_hour)

    if os.getenv("RUN_ON_STARTUP", "").lower() in ("1", "true", "yes"):
        logger.info("Startup update requested...")
        run_update()

    logger.info("Worker is running.")
    while not stop_event.is_set():
        time.sleep(1)

    logger.info("Worker shutting down.")
    scheduler.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())


