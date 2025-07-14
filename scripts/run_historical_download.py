#!/usr/bin/env python3
"""
Historical Invoice Download Runner
=================================

Simple runner script for common historical download scenarios.

Usage Examples:
    # Download all invoices from 2020 till today (default)
    python scripts/run_historical_download.py
    
    # Download from specific date range
    python scripts/run_historical_download.py --start 2024-01-01 --end 2023-01-01
    
    # Dry run to see what would be downloaded
    python scripts/run_historical_download.py --dry-run
    
    # Download last 2 years with verbose logging
    python scripts/run_historical_download.py --years 2 --verbose
    
    # Download last 6 months only
    python scripts/run_historical_download.py --months 6
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory for imports
sys.path.append(str(Path(__file__).parent.parent))

from scripts.historical_invoice_downloader import HistoricalInvoiceDownloader


def main():
    """Main function with simplified argument parsing"""
    parser = argparse.ArgumentParser(
        description='Historical Invoice Download Runner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    # Date range options
    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument('--years', type=int, 
                           help='Download last N years (e.g., --years 2)')
    date_group.add_argument('--months', type=int,
                           help='Download last N months (e.g., --months 6)')
    date_group.add_argument('--days', type=int,
                           help='Download last N days (e.g., --days 30)')
    
    # Custom date range
    parser.add_argument('--start', type=str, 
                       help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, 
                       help='End date (YYYY-MM-DD)')
    
    # Options
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview what would be downloaded without actually downloading')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable detailed logging')
    parser.add_argument('--force', action='store_true',
                       help='Reprocess existing invoices')
    
    args = parser.parse_args()
    
    # Determine date range
    end_date = datetime(2020, 1, 1)  # Default: back to 2020 (downloads from 2020 till today)
    start_date = datetime.now()      # Default: today
    
    if args.start and args.end:
        # Custom date range
        try:
            start_date = datetime.strptime(args.start, '%Y-%m-%d')
            end_date = datetime.strptime(args.end, '%Y-%m-%d')
        except ValueError as e:
            print(f"Error parsing dates: {e}")
            return 1
            
    elif args.years:
        # Last N years
        start_date = datetime.now()
        end_date = start_date - timedelta(days=args.years * 365)
        print(f"Downloading invoices from last {args.years} year(s)")
        
    elif args.months:
        # Last N months
        start_date = datetime.now()
        end_date = start_date - timedelta(days=args.months * 30)
        print(f"Downloading invoices from last {args.months} month(s)")
        
    elif args.days:
        # Last N days
        start_date = datetime.now()
        end_date = start_date - timedelta(days=args.days)
        print(f"Downloading invoices from last {args.days} day(s)")
        
    else:
        # Default: from 2020 till today
        print("Using default: downloading invoices from 2020 till today")
    
    if start_date <= end_date:
        print("Error: Start date must be after end date")
        return 1
    
    # Show what will be processed
    total_days = (start_date - end_date).days
    print(f"Date range: {start_date.date()} to {end_date.date()}")
    print(f"Total days to process: {total_days}")
    
    if args.dry_run:
        print("DRY RUN MODE: No files will be downloaded")
    
    # Confirm for large downloads
    if total_days > 365 and not args.dry_run:
        response = input(f"This will process {total_days} days of emails. Continue? (y/N): ")
        if response.lower() != 'y':
            print("Download cancelled.")
            return 0
    
    # Create and run downloader
    print("\nStarting historical invoice download...")
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
            print("\n✅ Historical download completed successfully!")
            return 0
        else:
            print("\n❌ Historical download failed!")
            return 1
            
    except KeyboardInterrupt:
        print("\n⚠️  Download interrupted by user")
        return 0
    except Exception as e:
        print(f"\n❌ Error during download: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main()) 