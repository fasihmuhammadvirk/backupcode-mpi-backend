"""
Main script for processing invoices using AI model extraction.

This script processes invoices from the database, extracts data using multiple
AI models (Gemini and OpenAI), compares results, and stores them in the database
with appropriate status flags indicating whether human review is required.
"""
import argparse
import time
import logging

from s3 import download_file_from_s3
from data_extraction import extract_and_validate_data
from db_utils import (
    add_model_extracted_data_batch_raw,
    get_supplier_from_invoice,
    get_invoices,
    claim_pending_extractions,
    mark_extraction_completed,
    mark_extraction_failed,
    mark_extraction_validation_failed,
    get_extraction_attempt_count,
    get_worst_validation_status,
)
from enums import ALL_MODELS as MODELS
from scripts.script_logger import get_script_logger

logger = logging.getLogger(__name__)


# TODO: return a dataclass that wraps any error so we can save it in the db to know why the extraction failed
def process_extraction(pdf_extraction_queue_id, file_path, s3_file_key=None, email_queue_id=None) -> bool:
    """
    Process a single PDF extraction queue item using AI models.

    This function extracts invoice data using AI models, compares the results
    line by line, and stores them in the database with appropriate status flags.
    Items are compared between models to determine if they match, and status is
    assigned accordingly. The tax amount is extracted from each model's output
    and stored with each line item record.

    Args:
        pdf_extraction_queue_id: UUID from pdf_extraction_queue table.
        file_path: Path to the local invoice file (PDF, image, etc.) to be processed.
        s3_file_key: Optional S3 key/path where the file was downloaded from.
            Used for S3 mode. Defaults to None for local mode.
        email_queue_id: Optional UUID linking to email_download_queue for queue mode.

    Returns:
        bool: True if data was successfully extracted and saved, False otherwise.

    Status Assignment Logic:
        - If both models extract the same item: status = "model_approved"
        - If models extract different items: status = "human_review_required"
        - If only one model extracts an item: status = "human_review_required"
    """
    try:
        if not file_path:
            logger.warning(f"Skipping queue item {pdf_extraction_queue_id}: No file path provided")
            return False

        logger.info(f"Processing queue item {pdf_extraction_queue_id}")

        data = extract_and_validate_data(MODELS, file_path)
        if data:
            result = add_model_extracted_data_batch_raw(MODELS, data, pdf_extraction_queue_id, file_path, s3_file_key, email_queue_id)
            if result is not None and result > 0:
                return True
        logger.error(f"Failed to extract data for queue item {pdf_extraction_queue_id}")
        return False
    except Exception as e:
        logger.exception(f"Error processing queue item {pdf_extraction_queue_id}: {e}")
        return False
        


def main():
    """
    Main entry point for the invoice processing script.

    Supports three modes:
    - S3 mode: Fetches invoices from database, downloads files from S3, processes them
    - Local mode: Fetches invoices from database, uses storage_path as local file path
    - Queue mode: Continuously polls pdf_extraction_queue for new items to process

    Command-line Arguments:
        --mode: Required. Either 's3', 'local', or 'queue'.
        --poll-interval: Seconds between polls (queue mode only, default 30)
        --batch-size: Items per batch (queue mode only, default 50)
        --idle-exit-after: Exit after N consecutive empty polls (queue mode only, 0 = never)

    The script processes invoices, extracts data using AI models, compares results,
    and stores them with appropriate status flags in the model_extracted_data table.

    To run alongside the bulk email downloader (`scripts/bulk_email_downloader.py`):
      # Terminal 1: Start bulk downloader                                                                                                                                                 
      uv run scripts/bulk_email_downloader.py run --start-date 2020-01-01                                                                                                                 
                                                                                               
      # Terminal 2: Start extraction with idle exit after 5 empty polls                                                                                                                   
      uv run scripts/backfill_invoices_data/main.py --mode queue --idle-exit-after 5           
                                                                                                                                                                                          
      # Or run forever                                                                                                                                                                    
      uv run scripts/backfill_invoices_data/main.py --mode queue  

    Include items that have failed validation
      # Include validation_failed items for retry (max 3 attempts)
      uv run scripts/backfill_invoices_data/main.py --mode queue --include-retries

      # Custom max retries
      uv run scripts/backfill_invoices_data/main.py --mode queue --include-retries --max-retries 5

    """
    parser = argparse.ArgumentParser(
        description='Process invoices using Gemini and OpenAI extraction'
    )
    parser.add_argument(
        '--mode',
        choices=['s3', 'local', 'queue'],
        required=True,
        help='Mode to run in: "s3" for S3 files, "local" for local files, '
             'or "queue" for continuous polling of pdf_extraction_queue'
    )
    parser.add_argument(
        '--poll-interval',
        type=int,
        default=30,
        help='Seconds between polls when queue is empty (queue mode only, default 30)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=50,
        help='Number of items to process per batch (queue mode only, default 50)'
    )
    parser.add_argument(
        '--idle-exit-after',
        type=int,
        default=0,
        help='Exit after N consecutive empty polls (queue mode only, 0 = never exit)'
    )
    parser.add_argument(
        '--include-retries',
        action='store_true',
        help='Include validation_failed items for retry (queue mode only)'
    )
    parser.add_argument(
        '--max-retries',
        type=int,
        default=3,
        help='Max extraction attempts before permanent failure (0 = unlimited, default 3)'
    )
    parser.add_argument(
        '--worker-id',
        type=int,
        help='Worker ID for multi-instance processing (used by multi_runner)'
    )

    args = parser.parse_args()

    if args.mode == 's3':
        logger.info("Running in S3 mode - fetching invoices from database...")
        invoices = get_invoices()
        if not invoices:
            logger.error("No invoices found in database")
            return

        for i, invoice in enumerate(invoices):
            logger.info(f"Downloading file from S3 for invoice {invoice['id']}")
            supplier_name = get_supplier_from_invoice(invoice['supplier_id'])
            if not supplier_name:
                logger.error(f"Failed to retrieve supplier for invoice {invoice['id']}")
                continue
            s3_path = f"{supplier_name}/{invoice['id']}.pdf"
            file_path = download_file_from_s3(s3_path)
            if not file_path:
                logger.error(f"Failed to download file from S3 for invoice {invoice['id']}")
                continue
            process_extraction(invoice['id'], file_path, s3_path)
            if i == 200:
                # We will evaluate 200 invoices to start and assess the output
                logger.info("Stopping early. Only evaluating 200 for now")
                break

    elif args.mode == 'local':
        invoices = get_invoices()
        if not invoices:
            logger.error("No invoices found in database")
            return

        for invoice in invoices:
            logger.info(f"Processing invoice {invoice['id']}")
            process_extraction(invoice['id'], invoice['storage_path'])

        logger.info("All invoices processed successfully")

    elif args.mode == 'queue':
        worker_info = f" (Worker {args.worker_id})" if args.worker_id else ""
        logger.info(f"Running in queue mode - continuous polling...{worker_info}")
        logger.info(f"  Poll interval: {args.poll_interval}s")
        logger.info(f"  Batch size: {args.batch_size}")
        logger.info(f"  Idle exit after: {args.idle_exit_after or 'never'}")
        logger.info(f"  Include retries: {args.include_retries}")
        logger.info(f"  Max retries: {args.max_retries or 'unlimited'}")
        if args.worker_id:
            logger.info(f"  Worker ID: {args.worker_id}")

        idle_count = 0  # Track consecutive empty polls

        while True:
            # Atomically claim batch of pending items (prevents race conditions with multiple instances)
            pending = claim_pending_extractions(
                limit=args.batch_size,
                include_validation_failed=args.include_retries
            )

            if not pending:
                idle_count += 1

                # Check idle exit condition
                if args.idle_exit_after > 0 and idle_count >= args.idle_exit_after:
                    logger.info(f"No items for {idle_count} consecutive polls. Exiting.")
                    break

                idle_status = f"{idle_count}/{args.idle_exit_after}" if args.idle_exit_after else f"{idle_count}/inf"
                logger.info(f"No pending items (idle {idle_status}), sleeping {args.poll_interval}s...")
                time.sleep(args.poll_interval)
                continue

            # Reset idle counter when we have work
            idle_count = 0
            logger.info(f"Found {len(pending)} pending extractions")

            # Process each item
            for item in pending:
                extraction_id = str(item['id'])
                s3_key = item['s3_key']
                is_retry = item.get('status') in ('validation_failed', 'completed')

                try:
                    # For 'completed' items picked up via bad extraction status, update queue status first
                    if item.get('status') == 'completed':
                        mark_extraction_validation_failed(extraction_id)
                        logger.info(f"Updated queue status from 'completed' to 'validation_failed' for {extraction_id}")

                    # Check retry limit before processing
                    if is_retry and args.max_retries > 0:
                        attempt_count = get_extraction_attempt_count(extraction_id)
                        if attempt_count >= args.max_retries:
                            logger.warning(
                                f"Max retries ({args.max_retries}) exceeded for {extraction_id}. "
                                f"Marking as permanently failed."
                            )
                            mark_extraction_failed(extraction_id, f"max_retries_exceeded ({attempt_count} attempts)")
                            continue
                        logger.info(f"Retry attempt {attempt_count + 1}/{args.max_retries} for {extraction_id}")

                    # Items are already marked as 'in_progress' by claim_pending_extractions()
                    logger.info(f"Processing extraction {extraction_id}" + (" (retry)" if is_retry else ""))

                    # Download PDF from S3 using s3_key directly
                    file_path = download_file_from_s3(s3_key)
                    if not file_path:
                        logger.error(f"Failed to download {s3_key}")
                        mark_extraction_failed(extraction_id, "S3 download failed")
                        continue

                    # Process extraction (uses existing extraction logic)
                    # Vendor/supplier is extracted by AI from the PDF
                    success = process_extraction(
                        pdf_extraction_queue_id=extraction_id,
                        file_path=file_path,
                        s3_file_key=s3_key,
                        email_queue_id=str(item.get('email_queue_id')) if item.get('email_queue_id') else None
                    )

                    if success:
                        # Check validation status of the extraction
                        worst_status = get_worst_validation_status(extraction_id)

                        if worst_status in ('low_confidence', 'human_review_required'):
                            mark_extraction_validation_failed(extraction_id)
                            logger.warning(
                                f"Extraction {extraction_id} has validation issues "
                                f"(worst_status={worst_status}). Marked for retry."
                            )
                        else:
                            mark_extraction_completed(extraction_id)
                            logger.info(f"Completed extraction {extraction_id}")
                    else:
                        mark_extraction_failed(extraction_id, "Extraction returned no data")
                        logger.warning(f"Failed extraction {extraction_id}: no data extracted")

                except Exception as e:
                    logger.exception(f"Error processing extraction {extraction_id}: {e}")
                    mark_extraction_failed(extraction_id, str(e))

            # Brief pause between batches
            time.sleep(1)

        logger.info("Queue processing complete")


if __name__ == "__main__":
    # Set up script-specific logging (file + stdout) and wire library loggers.
    # This only runs when the script is executed directly, not when imported as a library.
    logger = get_script_logger(__file__)
    for _lib_logger_name in ['mpi_backend', 'data_extraction', 'db_utils', 's3', 'pdf_utils', 'data_validation']:
        _lib_logger = logging.getLogger(_lib_logger_name)
        _lib_logger.setLevel(logging.INFO)
        for _handler in logger.handlers:
            _lib_logger.addHandler(_handler)

    main()
