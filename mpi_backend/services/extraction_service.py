"""
Extraction service -- claim pending PDF extractions and process them with AI models.
"""
import sys
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# TODO(cleanup): Remove sys.path hack once scripts/backfill_invoices_data
# is refactored into a proper package or its functions are moved into mpi_backend.
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts" / "backfill_invoices_data"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from scripts.backfill_invoices_data.main import process_extraction
from scripts.backfill_invoices_data.db_utils import (
    claim_pending_extractions,
    mark_extraction_completed,
    mark_extraction_failed,
    mark_extraction_validation_failed,
    get_worst_validation_status,
)
from scripts.backfill_invoices_data.s3 import download_file_from_s3


@dataclass
class ExtractionResult:
    """Result of an extraction run."""
    claimed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0


def run_extraction_loop(limit: int = 20) -> ExtractionResult:
    """
    Claim and process a batch of pending PDF extractions.

    Note: claim_pending_extractions manages its own DB connection (psycopg2).
    This function does NOT use db_context() because the extraction utilities
    use raw psycopg2 connections internally.
    """
    result = ExtractionResult()

    logger.info("Starting extraction trigger loop (limit=%d)", limit)

    # claim_pending_extractions manages its own DB connection
    pending = claim_pending_extractions(limit=limit)

    if not pending:
        logger.info("No pending extractions found in queue")
        return result

    result.claimed = len(pending)
    logger.info("Found %d extractions to process", result.claimed)

    for item in pending:
        extraction_id = str(item['id'])
        s3_key = item['s3_key']
        email_queue_id = str(item['email_queue_id'])

        try:
            logger.info("Processing extraction %s | S3: %s", extraction_id, s3_key)

            # Download PDF from S3
            file_path = download_file_from_s3(s3_key)
            if not file_path:
                logger.error("Failed to download %s from S3", s3_key)
                mark_extraction_failed(extraction_id, "S3 download failed")
                result.failed += 1
                continue

            # Process extraction using the AI models
            success = process_extraction(
                pdf_extraction_queue_id=extraction_id,
                file_path=file_path,
                s3_file_key=s3_key,
                email_queue_id=email_queue_id
            )

            if success:
                # Check validation status from the results just stored
                worst_status = get_worst_validation_status(extraction_id)
                if worst_status in ('low_confidence', 'human_review_required'):
                    mark_extraction_validation_failed(extraction_id)
                    logger.warning("Extraction %s validation check: %s", extraction_id, worst_status)
                    result.failed += 1
                else:
                    mark_extraction_completed(extraction_id)
                    logger.info("Successfully completed extraction %s", extraction_id)
                    result.succeeded += 1
            else:
                mark_extraction_failed(extraction_id, "AI extraction logic failed to return results")
                logger.warning("Failed extraction %s", extraction_id)
                result.failed += 1

        except Exception as e:
            logger.exception("Error in extraction loop for item %s: %s", extraction_id, e)
            result.failed += 1
            try:
                mark_extraction_failed(extraction_id, str(e))
            except Exception as err:
                logger.exception(
                    "Failed to mark extraction %s as failed: %s", extraction_id, err
                )

    logger.info("Extraction trigger loop complete")
    return result
