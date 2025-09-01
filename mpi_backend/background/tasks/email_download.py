"""
Email Download Task for Background Scheduler
Downloads emails and processes invoices automatically
"""

import asyncio
import logging


logger = logging.getLogger(__name__)

def download_emails():
    """Download emails and process invoices"""
    try:
        logger.info("Starting email download task")
        
        # Import the actual invoice downloader logic
        from mpi_backend.utils.invoice_downaloder import (
            email_download_background_task
        )
        
        # Run the invoice downloader asynchronously
        asyncio.run(email_download_background_task())
        
        logger.info("Email download task completed successfully")
        
    except Exception as e:
        logger.error(f"Email download task failed: {e}")
        raise
