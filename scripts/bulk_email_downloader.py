#!/usr/bin/env python3
"""
Bulk Email Downloader CLI using Gmail API
"""

import argparse
import sys
import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mpi_backend.config import SQLALCHEMY_DATABASE_URI
from mpi_backend.utils.email.gmail_client import GmailClient
from mpi_backend.utils.email.gmail_scanner import GmailScanner
from mpi_backend.utils.email.gmail_downloader import GmailDownloader
from scripts.script_logger import get_script_logger

logger = get_script_logger(__file__)
# Wire up library logging to script's handlers
mpi_logger = logging.getLogger('mpi_backend')
mpi_logger.setLevel(logging.INFO)
for handler in logger.handlers:
  mpi_logger.addHandler(handler)


def parse_domains(domains_str: str | None) -> list[str] | None:
    """Parse comma-separated domain/email list into lowercase stripped list."""
    if not domains_str:
        return None
    return [d.strip().lower() for d in domains_str.split(',') if d.strip()]


@contextmanager
def get_db_session():
    """Create database session with guaranteed cleanup"""
    engine = create_engine(SQLALCHEMY_DATABASE_URI)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def cmd_scan(args):
    """Scan emails and populate queue"""
    end_date_str = args.end_date if args.end_date else "present"
    logger.info(f"Scanning emails from {args.start_date} to {end_date_str} (timezone: {args.timezone})")

    with get_db_session() as session:
        with GmailClient() as client:
            scanner = GmailScanner(client, session)
            stats = scanner.scan_date_range(
                start_date=datetime.strptime(args.start_date, '%Y-%m-%d'),
                end_date=datetime.strptime(args.end_date, '%Y-%m-%d') if args.end_date else None,
                timezone=args.timezone,
                dry_run=args.dry_run,
                sender_filter=parse_domains(args.domains),
            )

        logger.info("Scan Results:")
        logger.info(f"  Emails scanned: {stats['scanned']}")
        logger.info(f"  Queued for download: {stats['queued']}")
        logger.info(f"  Skipped (already in queue): {stats['skipped']}")
        logger.info(f"  Errors: {stats['errors']}")


def cmd_download(args):
    """Process pending downloads"""
    logger.info(f"Processing downloads (batch_size={args.batch_size}, max_batches={args.max_batches})")
    domains = parse_domains(args.domains)

    with get_db_session() as session:
        with GmailClient() as client:
            downloader = GmailDownloader(client, session)

            stuck = downloader.reset_stuck(domains)
            if stuck > 0:
                logger.warning(f"Reset {stuck} stuck DOWNLOADING records from previous run")

            total_results = {'processed': 0, 'successful': 0, 'failed': 0, 'skipped': 0, 'partial': 0}

            for batch_num in range(args.max_batches):
                logger.info(f"Processing batch {batch_num + 1}/{args.max_batches}")
                result = downloader.process_batch(args.batch_size, domains)

                for key in total_results:
                    total_results[key] += getattr(result, key, 0)

                # Stop if no more pending
                if result.processed == 0:
                    logger.info("No more pending emails")
                    break

        logger.info("Download Results:")
        logger.info(f"  Total processed: {total_results['processed']}")
        logger.info(f"  Successful: {total_results['successful']}")
        logger.info(f"  Partial: {total_results['partial']}")
        logger.info(f"  Failed: {total_results['failed']}")
        logger.info(f"  Skipped (no PDF): {total_results['skipped']}")


def cmd_status(args):
    """Show queue status"""
    domains = parse_domains(args.domains)
    with get_db_session() as session:
        with GmailClient() as client:
            summary = GmailDownloader(client, session).get_status_summary(domains)

    counts = summary['counts']
    total = sum(counts.values())

    logger.info("\nEmail Download Queue Status")
    logger.info("=" * 40)
    logger.info(f"Total emails:     {total:,}")

    for status in ['PENDING', 'DOWNLOADING', 'DOWNLOADED', 'PARTIAL', 'FAILED', 'SKIPPED']:
        count = counts.get(status, 0)
        pct = (count / total * 100) if total > 0 else 0
        logger.info(f"  - {status:12}: {count:>8,}  ({pct:.1f}%)")

    logger.info(f"\nPDFs uploaded:    {summary['pdf_count']:,}")


def cmd_retry_failed(args):
    """Reset failed items for retry"""
    domains = parse_domains(args.domains)
    with get_db_session() as session:
        with GmailClient() as client:
            count = GmailDownloader(client, session).reset_failed(args.max_retries, domains)

    logger.info(f"Reset {count} failed items for retry")


def cmd_run(args):
    """Full pipeline: scan then download"""
    # First scan
    scan_args = argparse.Namespace(
        start_date=args.start_date,
        end_date=args.end_date,
        timezone=args.timezone,
        dry_run=False,
        domains=args.domains,
    )
    cmd_scan(scan_args)

    # Then download continuously
    download_args = argparse.Namespace(
        batch_size=args.batch_size,
        max_batches=999999,  # Run until complete
        domains=args.domains,
    )
    cmd_download(download_args)


def main():
    parser = argparse.ArgumentParser(description="""
     Bulk Email Downloader (Gmail API)

    Usage:
        python scripts/bulk_email_downloader.py scan --start-date 2020-01-01 --end-date 2025-01-08
        python scripts/bulk_email_downloader.py download --batch-size 50 --max-batches 100
        python scripts/bulk_email_downloader.py status
        python scripts/bulk_email_downloader.py retry-failed --max-retries 3
        python scripts/bulk_email_downloader.py run --start-date 2020-01-01
     """)
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # scan command
    scan_parser = subparsers.add_parser('scan', help='Scan emails and populate queue')
    scan_parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    scan_parser.add_argument('--end-date', default=None,
                            help='End date (YYYY-MM-DD), defaults to present if not specified')
    scan_parser.add_argument('--timezone', default='America/New_York',
                            help='Timezone for date interpretation (default: America/New_York)')
    scan_parser.add_argument('--dry-run', action='store_true', help='Preview mode')
    scan_parser.add_argument('--domains', default=None,
                             help='Comma-separated sender domains or emails to filter (e.g. @acme.com,bill@acme.com)')

    # download command
    dl_parser = subparsers.add_parser('download', help='Process pending downloads')
    dl_parser.add_argument('--batch-size', type=int, default=50, help='Emails per batch')
    dl_parser.add_argument('--max-batches', type=int, default=100, help='Max batches to process')
    dl_parser.add_argument('--domains', default=None,
                           help='Comma-separated sender domains or emails to filter (e.g. @acme.com,bill@acme.com)')

    # status command
    status_parser = subparsers.add_parser('status', help='Show queue status')
    status_parser.add_argument('--domains', default=None,
                               help='Comma-separated sender domains or emails to filter (e.g. @acme.com,bill@acme.com)')

    # retry-failed command
    retry_parser = subparsers.add_parser('retry-failed', help='Reset failed items')
    retry_parser.add_argument('--max-retries', type=int, default=3, help='Max retry count')
    retry_parser.add_argument('--domains', default=None,
                              help='Comma-separated sender domains or emails to filter (e.g. @acme.com,bill@acme.com)')

    # run command
    run_parser = subparsers.add_parser('run', help='Full pipeline (scan + download)')
    run_parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    run_parser.add_argument('--end-date', help='End date (YYYY-MM-DD), defaults to present if not specified')
    run_parser.add_argument('--timezone', default='America/New_York',
                            help='Timezone for date interpretation (default: America/New_York)')
    run_parser.add_argument('--batch-size', type=int, default=50, help='Emails per download batch')
    run_parser.add_argument('--domains', default=None,
                            help='Comma-separated sender domains or emails to filter (e.g. @acme.com,bill@acme.com)')

    args = parser.parse_args()

    if args.command == 'scan':
        cmd_scan(args)
    elif args.command == 'download':
        cmd_download(args)
    elif args.command == 'status':
        cmd_status(args)
    elif args.command == 'retry-failed':
        cmd_retry_failed(args)
    elif args.command == 'run':
        cmd_run(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
