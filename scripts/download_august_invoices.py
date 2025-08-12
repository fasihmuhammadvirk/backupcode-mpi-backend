#!/usr/bin/env python3
"""
Download all invoices for August of a given year by reusing the
HistoricalInvoiceDownloader pipeline (email -> attachments -> convert ->
process).

Usage:
  python scripts/download_august_invoices.py --year 2025 \
    [--dry-run] [--verbose] [--force]

Defaults:
  - --year: current year
  - August 1st to August 31st
"""

import sys
from pathlib import Path
from datetime import datetime
import argparse

# Ensure repo root is on path for imports
ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))

from mpi_backend.config.logging_config import setup_logging  # noqa: E402  E401
from scripts.historical_invoice_downloader import (  # noqa: E402  E401
    HistoricalInvoiceDownloader,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download all invoices for August of a given year"
    )
    parser.add_argument(
        "--year",
        type=int,
        default=datetime.now().year,
        help="Target year (default: current year)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without downloading",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable detailed logging"
    )
    parser.add_argument(
        "--force", action="store_true", help="Reprocess existing invoices"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=31,
        help="Days per batch (default: 31)",
    )

    args = parser.parse_args()

    # Setup logging like other scripts
    setup_logging()

    # August always has 31 days
    start_date = datetime(args.year, 8, 31)
    end_date = datetime(args.year, 8, 1)

    downloader = HistoricalInvoiceDownloader(
        start_date=start_date,
        end_date=end_date,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        verbose=args.verbose,
        force=args.force,
    )

    success = downloader.run_download()
    if not success:
        # Non-zero exit for CI visibility
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
