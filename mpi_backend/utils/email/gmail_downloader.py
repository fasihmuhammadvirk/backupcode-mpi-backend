"""
Attachment downloader using Gmail API.

Features:
- Direct attachment download (no full email fetch needed for small attachments)
- Stream to S3
- PDF filtering
- Queue status management
"""

import io
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass

import boto3
from sqlalchemy.orm import Session
from sqlalchemy import select, update, func, or_

from mpi_backend.database.models.EmailDownloadQueue import EmailDownloadQueue
from mpi_backend.utils.email.gmail_client import GmailClient
from mpi_backend.config import (
    REGION,
    INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY,
    INVOICES_PDFS_AWS_SERVER_SECRET_KEY,
    INVOICES_PDFS_BUCKET_NAME,
)
if (
    INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY is None or
    INVOICES_PDFS_AWS_SERVER_SECRET_KEY is None or
    INVOICES_PDFS_BUCKET_NAME is None
):
    raise RuntimeError(
        "Missing one of: INVOICES_PDFS_BUCKET_NAME, AWS_SERVER_PUBLIC_KEY, AWS_SERVER_SECRET_KEY"
    )


logger = logging.getLogger(__name__)

PDFS_ROOT_FOLDER = "invoices"


@dataclass
class ProcessingResult:
    processed: int
    successful: int
    failed: int
    skipped: int
    partial: int


class GmailDownloader:
    """Download attachments via Gmail API and upload to S3"""

    def __init__( self, gmail_client: GmailClient, db_session: Session, s3_bucket: str | None = None):
        self.client = gmail_client
        self.db = db_session

        self.s3_bucket = s3_bucket or INVOICES_PDFS_BUCKET_NAME

        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=INVOICES_PDFS_AWS_SERVER_PUBLIC_KEY,
            aws_secret_access_key=INVOICES_PDFS_AWS_SERVER_SECRET_KEY,
            region_name=REGION or "us-east-1"
        )

    def reset_stuck(self, domains: list[str] | None = None) -> int:
        """Reset stuck DOWNLOADING records to PENDING. Returns count reset."""
        q = update(EmailDownloadQueue).where(EmailDownloadQueue.status == 'DOWNLOADING')
        if domains:
            q = q.where(self._build_sender_filter(EmailDownloadQueue.sender, domains))
        result = self.db.execute(q.values(status='PENDING'))
        self.db.commit()
        return result.rowcount

    def reset_failed(self, max_retries: int, domains: list[str] | None = None) -> int:
        """Reset FAILED records under the retry limit to PENDING. Returns count reset."""
        q = (
            update(EmailDownloadQueue)
            .where(EmailDownloadQueue.status == 'FAILED')
            .where(EmailDownloadQueue.retry_count < max_retries)
        )
        if domains:
            q = q.where(self._build_sender_filter(EmailDownloadQueue.sender, domains))
        result = self.db.execute(q.values(status='PENDING', error_message=None))
        self.db.commit()
        return result.rowcount

    def get_status_summary(self, domains: list[str] | None = None) -> dict:
        """Return queue status counts by status and total PDFs uploaded."""
        q = select(
            EmailDownloadQueue.status,
            func.count(EmailDownloadQueue.id)
        ).group_by(EmailDownloadQueue.status)
        if domains:
            q = q.where(self._build_sender_filter(EmailDownloadQueue.sender, domains))
        status_rows = self.db.execute(q).all()

        pdf_q = (
            select(func.coalesce(func.sum(func.jsonb_array_length(EmailDownloadQueue.s3_keys)), 0))
            .where(EmailDownloadQueue.status.in_(['DOWNLOADED', 'PARTIAL']))
        )
        if domains:
            pdf_q = pdf_q.where(self._build_sender_filter(EmailDownloadQueue.sender, domains))
        pdf_count = self.db.execute(pdf_q).scalar() or 0

        return {
            'counts': {status: count for status, count in status_rows},
            'pdf_count': pdf_count,
        }

    def count_pending(self, domains: list[str] | None = None) -> int:
        """Return count of PENDING emails in the queue."""
        q = select(func.count(EmailDownloadQueue.id)).where(
            EmailDownloadQueue.status == EmailDownloadQueue.STATUS_PENDING
        )
        if domains:
            q = q.where(self._build_sender_filter(EmailDownloadQueue.sender, domains))
        return self.db.execute(q).scalar() or 0

    def process_batch(self, batch_size: int = 50, domains: list[str] | None = None) -> ProcessingResult:
        """Process next batch of pending emails"""
        result = ProcessingResult(processed=0, successful=0, failed=0, skipped=0, partial=0)

        # Fetch pending items
        q = (
            select(EmailDownloadQueue)
            .where(EmailDownloadQueue.status == EmailDownloadQueue.STATUS_PENDING)
            .order_by(EmailDownloadQueue.email_date.asc())
            .limit(batch_size)
        )
        if domains:
            q = q.where(self._build_sender_filter(EmailDownloadQueue.sender, domains))
        pending = self.db.execute(q).scalars().all()

        logger.info(f"Processing batch of {len(pending)} emails")

        for item in pending:
            result.processed += 1
            try:
                self._update_status(item, EmailDownloadQueue.STATUS_DOWNLOADING)
                status = self._download_email(item)

                if status == 'DOWNLOADED':
                    self._update_status(
                        item,
                        EmailDownloadQueue.STATUS_DOWNLOADED,
                        processed_at=datetime.now(timezone.utc)
                    )
                    result.successful += 1
                elif status == 'PARTIAL':
                    self._update_status(item, EmailDownloadQueue.STATUS_PARTIAL)
                    result.partial += 1
                elif status == 'FAILED':
                    self._update_status(item, EmailDownloadQueue.STATUS_FAILED)
                    result.failed += 1
                else:  # False = SKIPPED
                    result.skipped += 1

            except Exception as e:
                logger.exception("Failed to process")
                self._update_status(
                    item,
                    EmailDownloadQueue.STATUS_FAILED,
                    error_message=str(e),
                    increment_retry=True
                )
                result.failed += 1

        logger.info(f"Batch complete: {result}")
        return result

    def _download_email(self, queue_item: EmailDownloadQueue) -> str | bool:
        """Download attachments from single email.

        Returns:
            'DOWNLOADED' if all PDFs uploaded successfully
            'PARTIAL' if some PDFs uploaded but some failed
            'FAILED' if no PDFs uploaded (but PDFs were found)
            False if SKIPPED (no PDFs in email)
        """
        email_start = time.perf_counter()

        # Get full message
        fetch_start = time.perf_counter()
        message = self.client.get_message_full(queue_item.email_uid)
        logger.info(f"[TIMING] get_message_full: {time.perf_counter() - fetch_start:.2f}s")

        # Extract attachment info
        attachments = self.client.extract_attachments_info(message)

        # Filter to PDFs only
        pdf_attachments = [
            a for a in attachments
            if a['filename'].lower().endswith('.pdf')
        ]

        # Record expected counts BEFORE downloading
        queue_item.attachment_count = len(attachments)
        queue_item.in_email_pdf_count = len(pdf_attachments)
        self.db.commit()

        if not pdf_attachments:
            logger.info(f"No PDF attachments in {queue_item.email_uid}")
            self._update_status(queue_item, EmailDownloadQueue.STATUS_SKIPPED)
            return False

        s3_keys = []
        for attachment in pdf_attachments:
            # Download attachment
            dl_start = time.perf_counter()
            content = self.client.get_attachment(
                queue_item.email_uid,
                attachment['attachment_id']
            )
            logger.info(f"[TIMING] get_attachment ({attachment['filename']}): {time.perf_counter() - dl_start:.2f}s")

            # Upload to S3
            upload_start = time.perf_counter()
            s3_key = self._upload_to_s3(content, attachment['filename'], queue_item)
            logger.info(f"[TIMING] upload_to_s3 ({attachment['filename']}): {time.perf_counter() - upload_start:.2f}s")
            if s3_key:
                s3_keys.append(s3_key)

        # Update queue item with uploaded keys
        queue_item.s3_keys = s3_keys
        self.db.commit()

        # Determine status based on upload results
        uploaded = len(s3_keys)
        expected = queue_item.in_email_pdf_count

        logger.info(f"[TIMING] email_total ({queue_item.email_uid}): {time.perf_counter() - email_start:.2f}s")

        if uploaded == 0:
            return 'FAILED'
        elif uploaded == expected:
            return 'DOWNLOADED'
        else:
            return 'PARTIAL'

    def _upload_to_s3( self, content: bytes, filename: str, queue_item: EmailDownloadQueue) -> Optional[str]:
        """Upload attachment to S3"""
        try:
            # Generate S3 key
            sender_path = queue_item.sender.replace('@', '_at_') if '@' in queue_item.sender else 'unknown'
            date_prefix = queue_item.email_date.strftime('%Y-%m') if queue_item.email_date else 'unknown'
            safe_filename = "".join(c for c in filename if c.isalnum() or c in '._-')

            s3_key = f"{PDFS_ROOT_FOLDER}/{sender_path}/{date_prefix}/{queue_item.email_uid}_{safe_filename}"

            # Upload
            self.s3_client.upload_fileobj(
                io.BytesIO(content),
                self.s3_bucket,
                s3_key,
                ExtraArgs={'ContentType': 'application/pdf'}
            )

            logger.info(f"Uploaded to s3://{self.s3_bucket}/{s3_key}")
            return s3_key

        except Exception:
            logger.exception(f"S3 upload failed for {filename}")
            return None

    def _update_status(
        self,
        item: EmailDownloadQueue,
        status: str,
        error_message: str | None = None,
        processed_at: datetime | None = None,
        increment_retry: bool = False
    ):
        """Update queue item status"""
        item.status = status
        item.updated_at = datetime.now(timezone.utc)

        if error_message:
            item.error_message = error_message
        if processed_at:
            item.processed_at = processed_at
        if increment_retry:
            item.retry_count += 1

        self.db.commit()

    @staticmethod
    def _build_sender_filter(sender_col, domains: list[str]):
        """Build SQLAlchemy OR filter for domain/email list."""
        if not domains:
            raise ValueError("domains must be a non-empty list")
        conditions = []
        for d in domains:
            if d.startswith('@'):
                conditions.append(sender_col.ilike(f'%{d}'))
            else:
                conditions.append(sender_col == d)
        return or_(*conditions)
