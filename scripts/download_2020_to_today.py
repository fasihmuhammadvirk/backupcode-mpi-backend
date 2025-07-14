#!/usr/bin/env python3
"""
Download Invoices from 2020 to Today
====================================

Simple script to download all invoices from 2020 till today.
This is the recommended way to get a complete historical dataset.

Usage:
    python scripts/download_2020_to_today.py [options]

Options:
    --dry-run                  Preview what would be downloaded without actually downloading
    --verbose                  Enable detailed logging
    --force                    Reprocess existing invoices
    --confirm                  Skip confirmation prompt for large downloads
"""

import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory for imports
sys.path.append(str(Path(__file__).parent.parent))

from scripts.historical_invoice_downloader import HistoricalInvoiceDownloader


def main():
    """Main function for downloading invoices from 2020 to today"""
    parser = argparse.ArgumentParser(
        description='Download all invoices from 2020 till today',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    # Options
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview what would be downloaded without actually downloading')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable detailed logging')
    parser.add_argument('--force', action='store_true',
                       help='Reprocess existing invoices')
    parser.add_argument('--confirm', action='store_true',
                       help='Skip confirmation prompt for large downloads')
    
    args = parser.parse_args()
    
    # Set date range: from 2020-01-01 to today
    start_date = datetime.now()
    end_date = datetime(2020, 1, 1)
    
    # Calculate total days
    total_days = (start_date - end_date).days
    
    print("="*80)
    print("DOWNLOAD INVOICES FROM 2020 TO TODAY")
    print("="*80)
    print(f"Date range: {start_date.date()} to {end_date.date()}")
    print(f"Total days to process: {total_days:,}")
    print(f"Estimated time: {total_days * 0.5 / 60:.1f} hours (assuming 0.5 seconds per day)")
    
    if args.dry_run:
        print("\n🔍 DRY RUN MODE: No files will be downloaded")
    else:
        print("\n📥 LIVE MODE: Files will be downloaded and processed")
    
    print("="*80)
    
    # Confirm for large downloads (unless --confirm is used)
    if total_days > 365 and not args.dry_run and not args.confirm:
        print(f"\n⚠️  This will process {total_days:,} days of emails.")
        response = input("This is a large download. Continue? (y/N): ")
        if response.lower() != 'y':
            print("Download cancelled.")
            return 0
    
    # Create and run downloader
    print("\n🚀 Starting historical invoice download...")
    print("This will download all invoices from 2020 till today.")
    print("Progress will be logged to the console and log files.")
    print("-" * 80)
    
    downloader = HistoricalInvoiceDownloader(
        start_date=start_date,
        end_date=end_date,
        dry_run=args.dry_run,
        verbose=args.verbose,
        force=args.force
    )
    
    try:
        success = downloader.run_download()
        
        if success:
            print("\n" + "="*80)
            print("✅ HISTORICAL DOWNLOAD COMPLETED SUCCESSFULLY!")
            print("="*80)
            print("All invoices from 2020 till today have been downloaded and processed.")
            print("Check the logs for detailed statistics.")
            return 0
        else:
            print("\n" + "="*80)
            print("❌ HISTORICAL DOWNLOAD FAILED!")
            print("="*80)
            print("Check the logs for error details.")
            return 1
            
    except KeyboardInterrupt:
        print("\n" + "="*80)
        print("⚠️  DOWNLOAD INTERRUPTED BY USER")
        print("="*80)
        print("The download was stopped. You can restart it later.")
        return 0
    except Exception as e:
        print("\n" + "="*80)
        print("❌ CRITICAL ERROR DURING DOWNLOAD")
        print("="*80)
        print(f"Error: {e}")
        print("Check the logs for more details.")
        return 1


if __name__ == "__main__":
    sys.exit(main()) 