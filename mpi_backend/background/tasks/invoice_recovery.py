"""
Invoice Recovery Task for Background Scheduler
Recovers failed invoices automatically
"""

import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from mpi_backend.utils.failed_invoice_recovery import (
    process_failed_invoice_recovery
)

logger = logging.getLogger(__name__)


def recover_failed_invoices():
    """Recover failed invoices using the existing failed invoice
    recovery utility"""
    try:
        logger.info("Starting failed invoice recovery task")
        process_failed_invoice_recovery()
        logger.info("Failed invoice recovery task completed successfully")

    except Exception as e:
        logger.error(f"Failed invoice recovery task failed: {e}")
        raise
