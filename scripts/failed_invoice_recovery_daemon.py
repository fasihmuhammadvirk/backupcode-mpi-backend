#!/usr/bin/env python3
"""
failed_invoice_recovery_daemon.py

A daemon script to run failed invoice recovery as a background job.
This script can be scheduled to run daily using cron or a task scheduler.

USAGE:
  $ python scripts/failed_invoice_recovery_daemon.py

SCHEDULING:
  # Run daily at 2 AM
  0 2 * * * /path/to/python /path/to/scripts/failed_invoice_recovery_daemon.py
  
  # Run every 6 hours
  0 */6 * * * /path/to/python /path/to/scripts/failed_invoice_recovery_daemon.py

RECOMMENDED:
- Use a process manager to keep this script running in the background
- Logs will be written to the standard output and/or configured log file
- The script will automatically handle errors and restart if needed

"""
import time
import logging
import sys
import os
import signal
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from mpi_backend.config import TIMEZONE
from scripts.failed_invoice_recovery import process_failed_invoice_recovery

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
logger = logging.getLogger("failed_invoice_recovery_daemon")

# Configuration
RUN_INTERVAL_HOURS = 24  # Run every 24 hours
MAX_RETRIES = 3  # Maximum number of retries on failure
RETRY_DELAY_MINUTES = 30  # Delay between retries in minutes

# Global flag for graceful shutdown
shutdown_requested = False

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_requested = True

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def run_recovery_with_retries():
    """Run the recovery process with retry logic"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"Starting failed invoice recovery (attempt {attempt}/{MAX_RETRIES})")
            process_failed_invoice_recovery()
            logger.info("Failed invoice recovery completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed invoice recovery failed on attempt {attempt}: {str(e)}", exc_info=True)
            
            if attempt < MAX_RETRIES:
                logger.info(f"Retrying in {RETRY_DELAY_MINUTES} minutes...")
                time.sleep(RETRY_DELAY_MINUTES * 60)
            else:
                logger.error(f"Failed invoice recovery failed after {MAX_RETRIES} attempts")
                return False
    
    return False

def main():
    """Main daemon loop"""
    logger.info("Starting failed invoice recovery daemon")
    logger.info(f"Configuration: Run every {RUN_INTERVAL_HOURS} hours, Max retries: {MAX_RETRIES}")
    
    # Setup signal handlers
    setup_signal_handlers()
    
    # Track last run time
    last_run_time = None
    
    while not shutdown_requested:
        try:
            current_time = datetime.now(TIMEZONE)
            
            # Check if it's time to run
            should_run = False
            if last_run_time is None:
                # First run
                should_run = True
                logger.info("First run - starting immediately")
            else:
                # Check if enough time has passed
                time_since_last_run = current_time - last_run_time
                if time_since_last_run >= timedelta(hours=RUN_INTERVAL_HOURS):
                    should_run = True
                    logger.info(f"Time since last run: {time_since_last_run}, starting recovery")
                else:
                    time_until_next_run = timedelta(hours=RUN_INTERVAL_HOURS) - time_since_last_run
                    logger.debug(f"Time until next run: {time_until_next_run}")
            
            if should_run:
                # Run the recovery process
                success = run_recovery_with_retries()
                last_run_time = datetime.now(TIMEZONE)
                
                if success:
                    logger.info("Recovery completed successfully")
                else:
                    logger.error("Recovery failed after all retries")
                
                # Calculate next run time
                next_run_time = last_run_time + timedelta(hours=RUN_INTERVAL_HOURS)
                logger.info(f"Next scheduled run: {next_run_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Sleep for a shorter interval to check for shutdown signals
            sleep_interval = min(300, RUN_INTERVAL_HOURS * 3600)  # Sleep for 5 minutes or the run interval, whichever is shorter
            logger.debug(f"Sleeping for {sleep_interval} seconds")
            
            for _ in range(sleep_interval):
                if shutdown_requested:
                    break
                time.sleep(1)
                
        except Exception as e:
            logger.error(f"Unexpected error in daemon loop: {str(e)}", exc_info=True)
            logger.info("Sleeping for 5 minutes before retrying...")
            time.sleep(300)
    
    logger.info("Failed invoice recovery daemon stopped")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Failed invoice recovery daemon stopped by user (KeyboardInterrupt)")
    except Exception as e:
        logger.error(f"Fatal error in daemon: {str(e)}", exc_info=True)
        # Sleep and restart after fatal error
        time.sleep(60)
        logger.info("Restarting failed invoice recovery daemon after fatal error...")
        try:
            main()
        except Exception as e2:
            logger.critical(f"Repeated fatal error: {str(e2)}", exc_info=True)
            logger.info("Exiting after repeated fatal error.") 