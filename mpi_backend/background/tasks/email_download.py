"""
Email Download Task for Background Scheduler

Orchestrates two independent service phases:
  1. Scan Gmail + download attachments to S3
  2. Claim pending PDF extractions + run AI extraction

Each phase is best-effort: extraction runs even if scan/download fails,
because there may be previously-queued items waiting for extraction.
"""
import logging

from mpi_backend.services.email_download_service import scan_and_download
from mpi_backend.services.extraction_service import run_extraction_loop

logger = logging.getLogger(__name__)


def download_emails():
    """Download emails and process invoices."""
    logger.info("Starting email download task")

    # Scan + Download (best-effort)
    try:
        scan_download_result = scan_and_download()
        logger.info("Scan/download complete: %s", scan_download_result)
    except Exception as e:
        logger.exception("Scan/download phase failed: %s", e)

    # Extraction (best-effort, runs regardless of phase 1 outcome)
    try:
        extraction_result = run_extraction_loop()
        logger.info("Extraction complete: %s", extraction_result)
    except Exception as e:
        logger.exception("Extraction phase failed: %s", e)

    logger.info("Email download task finished")
