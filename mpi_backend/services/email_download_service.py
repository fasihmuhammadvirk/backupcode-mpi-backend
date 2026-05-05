"""
Email download service: scan Gmail for new invoices and download attachments.

Migrated from scripts/bulk_email_downloader.py.
Replaces the scan/download portion of mpi_backend/utils/invoice_downloader.py.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from mpi_backend.config import EMAIL_SCAN_HOURS, EMAIL_BATCH_SIZE, EMAIL_MAX_BATCHES, EMAIL_MAX_RETRIES
from mpi_backend.database import db_context
from mpi_backend.utils.email.gmail_client import GmailClient
from mpi_backend.utils.email.gmail_scanner import GmailScanner
from mpi_backend.utils.email.gmail_downloader import GmailDownloader, ProcessingResult

logger = logging.getLogger(__name__)


@dataclass
class ScanAndDownloadResult:
    """Result of a scan-and-download run."""
    scan_stats: dict = field(default_factory=lambda: {
        "scanned": 0, "queued": 0, "skipped": 0, "errors": 0
    })
    download_result: ProcessingResult | None = None
    stuck_reset: int = 0
    failed_reset: int = 0
    scan_error: str | None = None
    download_error: str | None = None


def scan_and_download(
    scan_hours: int = EMAIL_SCAN_HOURS,
    batch_size: int = EMAIL_BATCH_SIZE,
    max_batches: int = EMAIL_MAX_BATCHES,
    max_retries: int = EMAIL_MAX_RETRIES,
) -> ScanAndDownloadResult:
    """
    Scan Gmail for new invoices and download attachments to S3.

    Steps:
      1. Scan emails from (now - scan_hours) to present
      2. Reset stuck DOWNLOADING records from previous crashed runs
      3. Reset FAILED records under retry limit
      4. Download pending emails in batches (up to max_batches)

    Each step is best-effort: scan failure does not prevent download
    of previously-queued items.
    """
    result = ScanAndDownloadResult()

    with db_context() as session:
        with GmailClient() as client:
            # --- Scan ---
            try:
                scanner = GmailScanner(client, session)
                start_date = datetime.now() - timedelta(hours=scan_hours)
                result.scan_stats = scanner.scan_date_range(start_date=start_date)
                logger.info("Scan complete: %s", result.scan_stats)
            except Exception as e:
                logger.exception("Scan phase failed: %s", e)
                result.scan_error = str(e)

            # --- Reset stuck/failed ---
            downloader = GmailDownloader(client, session)
            try:
                result.stuck_reset = downloader.reset_stuck()
                if result.stuck_reset > 0:
                    logger.warning("Reset %d stuck DOWNLOADING records", result.stuck_reset)
            except Exception as e:
                logger.exception("reset_stuck failed: %s", e)

            try:
                result.failed_reset = downloader.reset_failed(max_retries=max_retries)
                if result.failed_reset > 0:
                    logger.info("Reset %d failed records for retry", result.failed_reset)
            except Exception as e:
                logger.exception("reset_failed failed: %s", e)

            # --- Download ---
            try:
                total = ProcessingResult(processed=0, successful=0, failed=0, skipped=0, partial=0)

                new_work = result.scan_stats.get("queued", 0) + result.stuck_reset + result.failed_reset
                if new_work == 0 and downloader.count_pending() == 0:
                    logger.info("No pending emails to download, skipping download phase")
                    result.download_result = total
                    return result

                for batch_num in range(max_batches):
                    logger.info("Processing download batch %d/%d", batch_num + 1, max_batches)
                    batch_result = downloader.process_batch(batch_size=batch_size)
                    total.processed += batch_result.processed
                    total.successful += batch_result.successful
                    total.failed += batch_result.failed
                    total.skipped += batch_result.skipped
                    total.partial += batch_result.partial
                    if batch_result.processed == 0:
                        logger.info("No more pending emails")
                        break
                result.download_result = total
                logger.info("Download complete: %s", total)
            except Exception as e:
                logger.exception("Download phase failed: %s", e)
                result.download_error = str(e)

    return result
