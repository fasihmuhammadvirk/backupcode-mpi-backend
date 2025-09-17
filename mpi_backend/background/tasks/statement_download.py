"""
Statement Download Task for Background Scheduler
Downloads statements automatically
"""

import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from mpi_backend.utils.statement_downloader import (
    statement_download_background_task
)

logger = logging.getLogger(__name__)


def download_statements():
    """Download statements using the existing statement downloader utility"""
    try:
        logger.info("Starting statement download task")
        statement_download_background_task()
        logger.info("Statement download task completed successfully")

    except Exception as e:
        logger.error(f"Statement download task failed: {e}")
        raise
