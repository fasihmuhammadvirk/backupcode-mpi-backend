"""
Email scanner using Gmail API.

Features:
- Uses Gmail search syntax (same as web UI)
- Filters by sender whitelist
- Populates database queue
- Timezone-aware date filtering using Unix timestamps
"""

import logging
import pytz
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from mpi_backend.database.models.SupplierEmailPattern import SupplierEmailPattern
from mpi_backend.database.models.EmailDownloadQueue import EmailDownloadQueue
from mpi_backend.utils.email.gmail_client import GmailClient
from mpi_backend.config import TIMEZONE

logger = logging.getLogger(__name__)


class GmailScanner:
    """Scan Gmail and populate download queue"""

    def __init__(self, gmail_client: GmailClient, db_session: Session):
        """Build sender whitelist from active SupplierEmailPattern rows."""
        self.client = gmail_client
        self.db = db_session

        mappings = (
            self.db.query(SupplierEmailPattern)
            .filter(SupplierEmailPattern.is_active.is_(True))
            .all()
        )
        # Sort by length descending so full emails are checked before domains
        self.sender_whitelist = sorted(
            [m.sender_pattern.lower() for m in mappings],
            key=len,
            reverse=True,
        )

    def scan_date_range(
        self,
        start_date: datetime,
        end_date: datetime | None = None,
        timezone: str = str(TIMEZONE),
        dry_run: bool = False,
        sender_filter: list[str] | None = None,
    ) -> dict:
        """
        Scan emails in date range using Gmail search.

        Note: We convert the dates to Unix timestamps in the specified timezone
        because Gmail's API works from UTC. So when we make the conversion
        we convert the user-provide dates to UTC and make sure we only get the
        data within these dates.

        Sources:
        - https://developers.google.com/gmail/api/guides/filtering
        - https://github.com/googleapis/google-api-nodejs-client/issues/3290

        Args:
            start_date: Start of range (inclusive)
            end_date: End of range (inclusive), or None for open-ended
            timezone: Timezone for date interpretation (default: America/New_York)
            dry_run: If True, don't insert into database

        Returns:
            Stats dict with scanned, queued, skipped, errors counts
        """
        stats = {'scanned': 0, 'queued': 0, 'skipped': 0, 'errors': 0}

        # Apply sender filter to whitelist
        if sender_filter:
            def _matches(pattern: str) -> bool:
                for f in sender_filter:
                    if f.startswith('@'):
                        # domain filter matches domain patterns and specific emails at that domain
                        if pattern == f or pattern.endswith(f):
                            return True
                    else:
                        # specific email filter: matches exact pattern OR a domain pattern that covers it
                        if pattern == f:
                            return True
                        if pattern.startswith('@') and f.endswith(pattern):
                            # whitelist has @acme.com, filter has invoices@acme.com
                            return True
                return False
            whitelist = [p for p in self.sender_whitelist if _matches(p)]
            if not whitelist:
                logger.warning(
                    f"sender_filter {sender_filter!r} matched no entries in sender_whitelist. "
                    f"Available patterns: {self.sender_whitelist}"
                )
        else:
            whitelist = self.sender_whitelist

        # Convert dates to Unix timestamps in the specified timezone
        # This ensures precise timezone-aware filtering
        tz = pytz.timezone(timezone)

        # Make start_date timezone-aware (midnight in user's timezone)
        start_dt = tz.localize(datetime.combine(start_date.date(), datetime.min.time()))
        after_ts = int(start_dt.timestamp())

        before_ts = None
        end_dt = None
        if end_date:
            # End date at midnight of the next day (inclusive of end_date)
            end_dt = tz.localize(datetime.combine(end_date.date() + timedelta(days=1), datetime.min.time()))
            before_ts = int(end_dt.timestamp())

        n_vendors = len(whitelist)
        total_messages = 0

        for sender_item in whitelist:
            try:
                # Build query with Unix timestamps for precise timezone handling
                # If it's a domain (starts with @), use wildcard to match any user at that domain
                from_filter = f"*{sender_item}" if sender_item.startswith('@') else sender_item

                if before_ts:
                    query = f"from:{from_filter} after:{after_ts} before:{before_ts}"
                    logger.debug(f"Searching emails matching from:{from_filter} between {start_dt.strftime('%Y-%m-%d %Z')} and {end_dt.strftime('%Y-%m-%d %Z')}")
                else:
                    query = f"from:{from_filter} after:{after_ts}"
                    logger.debug(f"Searching emails matching from:{from_filter} after {start_dt.strftime('%Y-%m-%d %Z')}")

                messages = self.client.search_messages(query, max_results=10000)
                logger.debug(f"Found {len(messages)} messages for {sender_item}")
                total_messages += len(messages)

                for msg_ref in messages:
                    stats['scanned'] += 1
                    try:
                        # Get metadata
                        metadata = self.client.get_message_metadata(msg_ref['id'])
                        headers = metadata['headers']

                        if dry_run:
                            logger.info(
                                f"[DRY RUN] Would queue: {msg_ref['id']} "
                                f"- {headers.get('Subject', 'No Subject')}"
                            )
                            stats['queued'] += 1
                            continue

                        # Queue the email
                        if self._queue_email(msg_ref['id'], metadata):
                            stats['queued'] += 1
                        else:
                            stats['skipped'] += 1

                    except Exception as e:
                        logger.error(f"Error processing {msg_ref['id']}: {e}")
                        stats['errors'] += 1

                # Commit after each sender batch
                if not dry_run:
                    self.db.commit()

            except Exception as e:
                logger.error(f"Error scanning sender {sender_item}: {e}")
                stats['errors'] += 1

        logger.info(
            f"Scan complete: {n_vendors} vendors searched, {total_messages} messages found "
            f"| queued={stats['queued']} skipped={stats['skipped']} errors={stats['errors']}"
        )
        return stats

    def _queue_email(self, message_id: str, metadata: dict) -> bool:
        """Insert email into download queue (idempotent)"""
        try:
            headers = metadata['headers']

            # Parse sender email from "Name <email>" format
            from_header = headers.get('From', '')
            if '<' in from_header and '>' in from_header:
                sender = from_header.split('<')[1].split('>')[0].lower().strip()
            else:
                sender = from_header.lower().strip()

            # Parse date
            date_str = headers.get('Date', '')
            try:
                email_date = parsedate_to_datetime(date_str) if date_str else None
            except Exception:
                email_date = None

            stmt = insert(EmailDownloadQueue).values(
                email_uid=message_id,  # Gmail message ID
                message_id=headers.get('Message-ID', ''),
                sender=sender,
                subject=headers.get('Subject', ''),
                email_date=email_date,
                status=EmailDownloadQueue.STATUS_PENDING
            ).on_conflict_do_nothing(index_elements=['email_uid'])

            result = self.db.execute(stmt)
            return result.rowcount > 0

        except Exception as e:
            logger.error(f"Failed to queue {message_id}: {e}")
            self.db.rollback()
            return False
