import logging
import os
import sys
import time
import signal
from threading import Event

from .data_builder import update_scryfall_data
from .logging_config import setup_loggers

# Set up logger
setup_loggers()
logger = logging.getLogger("oracle_tutor_api.worker")

# Global control event
stop_event = Event()

def signal_handler(signum, frame):
    logger.info(f"Signal {signum} received. Shutting down worker...")
    stop_event.set()

def main():
    """
    Worker entry point.
    Runs a blocking scheduler loop.
    """
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("Oracle Tutor Worker Starting...")
    
    # 1. Load Model
    logger.info("Loading embedding model for ingestion...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('all-MiniLM-L6-v2')
    logger.info("Loaded standard PyTorch model.")
        
    # 2. Setup Scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        
        def run_update():
            """Run update process."""
            try:
                logger.info("Running scheduled database update...")
                updated = update_scryfall_data(force=False, model=model)
                if updated:
                    logger.info("Scheduled update completed successfully.")
                else:
                    logger.info("No updates found.")
            except Exception as e:
                logger.error(f"Error in scheduled update: {e}", exc_info=True)
        
        # Default to 2:00 AM
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
        logger.info(f"Scheduler started (Daily at {update_hour}:00).")
        
        # Optional: Run once on startup if requested
        if os.getenv("RUN_ON_STARTUP", "").lower() in ("1", "true", "yes"):
            logger.info("Startup update requested...")
            run_update()
            
    except ImportError:
        logger.error("APScheduler not installed. Worker cannot run schedules.")
        return 1
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
        return 1
        
    # 3. Keep Alive
    logger.info("Worker is running. Press Ctrl+C to exit.")
    
    # Simple keep-alive loop
    while not stop_event.is_set():
        time.sleep(1)
        
    logger.info("Worker shutting down.")
    scheduler.shutdown()
    return 0

if __name__ == "__main__":
    sys.exit(main())
