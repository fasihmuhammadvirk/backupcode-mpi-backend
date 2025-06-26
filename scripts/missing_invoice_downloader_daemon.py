#!/usr/bin/env python3
"""
missing_invoice_downloader_daemon.py

A standalone script to download missing invoices from the past 15 years.
- Runs as a long-lived background process (daemon-style)
- Designed to be managed by a process manager (systemd, supervisord, etc.)
- Does NOT mark any emails as read
- Logs progress and errors
- Scans emails in manageable time chunks (e.g., by month)

USAGE:
  $ python scripts/missing_invoice_downloader_daemon.py

RECOMMENDED:
- Use a process manager to keep this script running in the background.
- Logs will be written to the standard output and/or configured log file.

"""
import time
import logging
from datetime import datetime, timedelta
from mpi_backend.utils import missing_invoice_downaloder as downloader
from mpi_backend.config import TIMEZONE

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
logger = logging.getLogger("missing_invoice_downloader_daemon")

# How many years back to scan
YEARS_BACK = 15
# How many days per chunk (e.g., 30 = monthly)
DAYS_PER_CHUNK = 30
# How long to sleep between chunks (seconds)
SLEEP_BETWEEN_CHUNKS = 5


def daterange(start_date, end_date, delta_days):
    """Yield (start, end) tuples for each chunk between start_date and end_date."""
    current = start_date
    while current < end_date:
        next_chunk = min(current + timedelta(days=delta_days), end_date)
        yield current, next_chunk
        current = next_chunk


def main():
    logger.info(
        "Starting missing invoice downloader daemon for past %d years",
        YEARS_BACK
    )
    now = datetime.now(TIMEZONE)
    start_date = now - timedelta(days=YEARS_BACK * 365)
    end_date = now

    while True:
        logger.info(
            "Beginning full scan from %s to %s",
            start_date.strftime('%Y-%m-%d'),
            end_date.strftime('%Y-%m-%d')
        )
        for chunk_start, chunk_end in daterange(start_date, end_date, DAYS_PER_CHUNK):
            # IMAP date format: 'DD-Mon-YYYY'
            start_str = chunk_start.strftime('%d-%b-%Y')
            end_str = chunk_end.strftime('%d-%b-%Y')
            logger.info(
                f"Scanning emails from {start_str} to {end_str} (exclusive)"
            )
            try:
                mail = downloader.login()
                filtered_ids = downloader.search_emails_between_dates(
                    mail, start_str, end_str
                )
                logger.info(f"Found {len(filtered_ids)} emails in chunk")
                for idx, e_id in enumerate(filtered_ids, 1):
                    try:
                        logger.info(
                            f"Processing email {idx}/{len(filtered_ids)} - UID: {e_id}"
                        )
                        result, response = mail.uid('fetch', e_id, '(BODY.PEEK[])')
                        if result != 'OK' or not response or not response[0]:
                            logger.error(f"Failed to fetch email UID {e_id}")
                            continue
                        try:
                            raw_email = response[0][1].decode('utf-8')
                        except UnicodeDecodeError:
                            raw_email = response[0][1].decode('latin-1')
                        email_message = downloader.email.message_from_string(raw_email)
                        downloader.download_email_attachments(
                            email_message, downloader.INVOICE_DOWNLOAD_FOLDER
                        )
                    except Exception as email_error:
                        logger.error(
                            f"Failed to process email UID {e_id}: {str(email_error)}"
                        )
                        continue
                mail.close()
                mail.logout()
            except Exception as chunk_error:
                logger.error(
                    f"Error processing chunk {start_str} to {end_str}: {str(chunk_error)}"
                )
            logger.info(
                f"Sleeping {SLEEP_BETWEEN_CHUNKS} seconds before next chunk..."
            )
            time.sleep(SLEEP_BETWEEN_CHUNKS)
        logger.info(
            "Completed full scan. Sleeping 1 hour before restarting full scan..."
        )
        time.sleep(3600)  # Sleep 1 hour before starting over


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info(
            "Missing invoice downloader daemon stopped by user (KeyboardInterrupt)"
        )
    except Exception as e:
        logger.error(
            f"Fatal error in daemon: {str(e)}", exc_info=True
        )
        # Sleep and restart after fatal error
        time.sleep(60)
        logger.info(
            "Restarting missing invoice downloader daemon after fatal error..."
        )
        try:
            main()
        except Exception as e2:
            logger.critical(
                f"Repeated fatal error: {str(e2)}", exc_info=True
            )
            logger.info(
                "Exiting after repeated fatal error."
            ) 