"""
Missing Invoice Download Task for Background Scheduler
Downloads missing invoices automatically
"""

import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from mpi_backend.utils.missing_invoice_downaloder import (
    missing_email_download_background_task
)

logger = logging.getLogger(__name__)


def download_missing_invoices():
    """Download missing invoices using the existing missing invoice
    downloader utility"""
    try:
        logger.info("Starting missing invoice download task")
        missing_email_download_background_task()
        logger.info("Missing invoice download task completed successfully")

    except Exception as e:
        logger.error(f"Missing invoice download task failed: {e}")
        raise
