"""
Email Download Task for Background Scheduler
Downloads emails and processes invoices automatically
"""

import logging

logger = logging.getLogger(__name__)

def download_emails():
    """Download emails and process invoices"""
    try:
        logger.info("Starting email download task")
        
        # Import the actual download logic
        from download_past_49_hours import download_last_4_days_invoices
        
        # Run the download
        download_last_4_days_invoices()
        
        logger.info("Email download task completed successfully")
        
    except Exception as e:
        logger.error(f"Email download task failed: {e}")
        raise
