#!/usr/bin/env python3
"""
Monthly Statement Downloader and Processor for Last Year
========================================================

This script downloads and processes monthly statements from email for the last year.
It handles:
- Email connection and search for statement emails
- PDF download and processing
- Data extraction and database storage
- S3 upload for storage
- Duplicate detection and error handling

Usage:
    python scripts/download_last_year_statements.py [options]

Options:
    --from-months-ago INT    Number of months ago to start from (default: 12)
    --to-months-ago INT      Number of months ago to end at (default: 0)
    --suppliers TEXT         Comma-separated list of suppliers to process
    --dry-run               Preview what would be processed without downloading
    --force                 Reprocess existing statements
    --verbose               Enable detailed logging
"""

import sys
import os
import argparse
import logging
import imaplib
import email
import re
from pathlib import Path
from datetime import datetime, timedelta, date
from contextlib import contextmanager
from typing import List, Optional, Dict, Any
from collections import defaultdict
import time

# Add the parent directory to the path so we can import mpi_backend
sys.path.append(str(Path(__file__).parent.parent))

from mpi_backend.config import (
    SMTP_SERVER, LOGIN_EMAIL, LOGIN_PWD, TIMEZONE,
    INVOICE_DOWNLOAD_FOLDER
)
from mpi_backend.database import get_db
from mpi_backend.database.models.statement_models import (
    PlumbingSupplier, PlumbingStatement, PlumbingInvoice
)
from mpi_backend.utils.statement_extractor.extractor import StatementExtractor
from mpi_backend.utils.s3_utils import upload_file
from mpi_backend.database.controllers.statement_controller import (
    StatementController
)

# Configure logging
logger = logging.getLogger(__name__)

# Statement suppliers that send monthly statements
STATEMENT_SUPPLIERS = [
    "BMW Plumbing Supplies",
    "World Wide Plumbing", 
    "Y & S Plumbing Supply",
    "Supreme Plumbing Supply",
    "Pyramid Plumbing",
    "ABC Opus Services",
    "Park Plumbing Supply",
    "Gotham Plumbing Supply",
    "FW Webb Plumbing Supply",
    "Flow Mark Plumbing Supply"
]

# Email patterns for each supplier
SUPPLIER_EMAIL_PATTERNS = {
    "BMW Plumbing Supplies": ["bmw", "bmwpsupply"],
    "World Wide Plumbing": ["world wide", "wwps"],
    "Y & S Plumbing Supply": ["y&s", "ysplumbing", "y s plumbing"],
    "Supreme Plumbing Supply": ["supreme", "supremeplumbingnj"],
    "Pyramid Plumbing": ["pyramid", "pyramidps"],
    "ABC Opus Services": ["abc opus", "opusoperations"],
    "Park Plumbing Supply": ["park plumbing", "parkplumbingsupply"],
    "Gotham Plumbing Supply": ["gotham"],
    "FW Webb Plumbing Supply": ["webb", "fwwebb"],
    "Flow Mark Plumbing Supply": ["flow mark", "flowmarksupply"]
}

# Keywords that indicate statement emails
STATEMENT_KEYWORDS = [
    'monthly statement',
    'statement',
    'aging report',
    'account statement',
    'monthly aging',
    'balance forward',
    'account summary'
]


class StatementDownloader:
    """Enhanced statement downloader for historical data"""
    
    def __init__(self, dry_run=False, force=False, verbose=False):
        self.dry_run = dry_run
        self.force = force
        self.verbose = verbose
        self.mail = None
        self.db_session = None
        self.controller = None
        
        # Statistics tracking
        self.stats = {
            'emails_searched': 0,
            'emails_found': 0,
            'pdfs_downloaded': 0,
            'statements_processed': 0,
            'statements_saved': 0,
            'errors': 0,
            'skipped_existing': 0
        }
        
        # Setup logging
        log_level = logging.DEBUG if verbose else logging.INFO
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(
                    f'statement_download_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
                )
            ]
        )
    
    def __enter__(self):
        """Context manager entry"""
        self.connect_to_email()
        self.connect_to_database()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.cleanup()
    
    def connect_to_email(self):
        """Establish IMAP connection"""
        try:
            logger.info("Connecting to email server...")
            self.mail = imaplib.IMAP4_SSL(SMTP_SERVER)
            self.mail.login(LOGIN_EMAIL, LOGIN_PWD)
            self.mail.select('inbox')
            logger.info("Successfully connected to email")
        except Exception as e:
            logger.error(f"Failed to connect to email: {str(e)}")
            raise
    
    def connect_to_database(self):
        """Establish database connection"""
        try:
            logger.info("Connecting to database...")
            db_context = contextmanager(get_db)
            self.db_session = db_context().__enter__()
            self.controller = StatementController(self.db_session)
            logger.info("Successfully connected to database")
        except Exception as e:
            logger.error(f"Failed to connect to database: {str(e)}")
            raise
    
    def cleanup(self):
        """Clean up connections"""
        try:
            if self.mail:
                self.mail.close()
                self.mail.logout()
                logger.info("Email connection closed")
        except Exception as e:
            logger.warning(f"Error closing email connection: {str(e)}")
        
        try:
            if self.db_session:
                self.db_session.close()
                logger.info("Database connection closed")
        except Exception as e:
            logger.warning(f"Error closing database connection: {str(e)}")
    
    def generate_date_ranges(self, from_months_ago: int, to_months_ago: int) -> List[tuple]:
        """Generate date ranges for each month to search"""
        date_ranges = []
        current_date = datetime.now(TIMEZONE)
        
        for months_back in range(to_months_ago, from_months_ago + 1):
            # Calculate target month
            target_date = current_date - timedelta(days=months_back * 30)
            
            # Get first and last day of that month
            first_day = target_date.replace(day=1)
            if target_date.month == 12:
                last_day = target_date.replace(year=target_date.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                last_day = target_date.replace(month=target_date.month + 1, day=1) - timedelta(days=1)
            
            date_ranges.append((first_day, last_day))
        
        return date_ranges
    
    def ensure_suppliers_exist(self):
        """Ensure all statement suppliers exist in database"""
        try:
            logger.info("Ensuring all suppliers exist in database...")
            
            for supplier_name in STATEMENT_SUPPLIERS:
                existing = self.db_session.query(PlumbingSupplier).filter(
                    PlumbingSupplier.name == supplier_name
                ).first()
                
                if not existing:
                    supplier = PlumbingSupplier(
                        name=supplier_name,
                        is_active="Active"
                    )
                    self.db_session.add(supplier)
                    logger.info(f"Created supplier: {supplier_name}")
            
            self.db_session.commit()
            logger.info("All suppliers verified in database")
            
        except Exception as e:
            logger.error(f"Error ensuring suppliers exist: {str(e)}")
            self.db_session.rollback()
            raise
    
    def detect_supplier_from_email(self, email_subject: str, sender_email: str) -> Optional[str]:
        """Detect supplier from email subject and sender"""
        try:
            subject = (email_subject or "").lower()
            sender = (sender_email or "").lower()
            
            for supplier_name, patterns in SUPPLIER_EMAIL_PATTERNS.items():
                for pattern in patterns:
                    if pattern.lower() in subject or pattern.lower() in sender:
                        return supplier_name
            
            # Log unknown suppliers for manual review
            logger.warning(f"Unknown supplier - Subject: {email_subject}, Sender: {sender_email}")
            return None
            
        except Exception as e:
            logger.error(f"Error detecting supplier: {str(e)}")
            return None
    
    def extract_statement_date_from_subject(self, subject: str) -> Optional[datetime]:
        """Extract statement date from email subject"""
        try:
            # Common patterns for statement dates in subjects
            date_patterns = [
                r'(\d{1,2}/\d{1,2}/\d{2,4})',  # MM/DD/YYYY or M/D/YY
                r'(\d{1,2}-\d{1,2}-\d{2,4})',  # MM-DD-YYYY
                r'(\w+\s+\d{4})',              # Month YYYY (e.g., "April 2024")
                r'(\d{4}-\d{2})',              # YYYY-MM
            ]
            
            for pattern in date_patterns:
                match = re.search(pattern, subject)
                if match:
                    date_str = match.group(1)
                    try:
                        # Try different date formats
                        for fmt in ['%m/%d/%Y', '%m/%d/%y', '%m-%d-%Y', 
                                    '%B %Y', '%Y-%m']:
                            try:
                                return datetime.strptime(date_str, fmt)
                            except ValueError:
                                continue
                    except Exception:
                        continue
            
            # Default to current month if no date found
            return datetime.now()
            
        except Exception as e:
            logger.error(f"Date extraction failed: {str(e)}")
            return datetime.now()
    
    def search_emails_for_date_range(self, start_date: datetime, end_date: datetime) -> List[str]:
        """Search for statement emails in a specific date range"""
        try:
            # Format dates for IMAP search
            since_date = start_date.strftime('%d-%b-%Y')
            before_date = (end_date + timedelta(days=1)).strftime('%d-%b-%Y')
            
            logger.info(f"Searching emails from {since_date} to {end_date.strftime('%d-%b-%Y')}")
            
            # Build search criteria
            keyword_criteria = []
            for keyword in STATEMENT_KEYWORDS:
                keyword_criteria.append(f'SUBJECT "{keyword}"')
            
            search_query = f'(SINCE {since_date} BEFORE {before_date} ({" OR ".join(keyword_criteria)}))'
            
            if self.verbose:
                logger.debug(f"Search query: {search_query}")
            
            # Execute search
            result, data = self.mail.uid('search', None, search_query)
            if result != 'OK':
                logger.error(f"Email search failed: {result}")
                return []
            
            email_ids = data[0].split() if data[0] else []
            self.stats['emails_found'] += len(email_ids)
            
            logger.info(f"Found {len(email_ids)} potential statement emails")
            return [eid.decode('utf-8') if isinstance(eid, bytes) else eid for eid in email_ids]
            
        except Exception as e:
            logger.error(f"Error searching emails: {str(e)}")
            return []
    
    def statement_already_exists(self, supplier_name: str, statement_date: datetime) -> bool:
        """Check if statement already exists for supplier and month"""
        try:
            # Get supplier
            supplier = self.db_session.query(PlumbingSupplier).filter(
                PlumbingSupplier.name == supplier_name
            ).first()
            
            if not supplier:
                return False
            
            # Check if statement exists for this month/year
            month_start = statement_date.replace(day=1)
            if statement_date.month == 12:
                next_month = statement_date.replace(year=statement_date.year + 1, month=1, day=1)
            else:
                next_month = statement_date.replace(month=statement_date.month + 1, day=1)
            
            existing_statement = self.db_session.query(PlumbingStatement).filter(
                PlumbingStatement.supplier_id == supplier.id,
                PlumbingStatement.statement_date >= month_start.date(),
                PlumbingStatement.statement_date < next_month.date()
            ).first()
            
            return existing_statement is not None
            
        except Exception as e:
            logger.error(f"Error checking statement existence: {str(e)}")
            return False
    
    def download_attachments_from_email(self, email_id: str, base_folder: Path) -> List[str]:
        """Download PDF attachments from a specific email"""
        try:
            # Fetch email
            result, response = self.mail.uid('fetch', email_id, '(BODY.PEEK[])')
            if result != 'OK' or not response or not response[0]:
                logger.error(f"Failed to fetch email UID {email_id}")
                return []
            
            # Parse email
            try:
                raw_email = response[0][1].decode('utf-8')
            except UnicodeDecodeError:
                raw_email = response[0][1].decode('latin-1')
            
            email_message = email.message_from_string(raw_email)
            
            # Get email metadata
            subject = email_message.get('Subject', '')
            sender = email.utils.parseaddr(email_message.get('From', ''))[1]
            
            # Detect supplier
            supplier_name = self.detect_supplier_from_email(subject, sender)
            if not supplier_name:
                logger.warning(f"Cannot detect supplier for email {email_id}, skipping")
                return []
            
            # Extract statement date
            statement_date = self.extract_statement_date_from_subject(subject)
            
            # Check if already exists (unless force mode)
            if not self.force and self.statement_already_exists(supplier_name, statement_date):
                logger.info(f"Statement already exists for {supplier_name} - {statement_date.strftime('%Y-%m')}, skipping")
                self.stats['skipped_existing'] += 1
                return []
            
            # Download attachments
            downloaded_files = []
            
            for part in email_message.walk():
                try:
                    if (part.get_content_maintype() != 'multipart' and 
                            part.get('Content-Disposition') is not None):
                        
                        filename = part.get_filename()
                        if not filename or not filename.lower().endswith(('.pdf', '.PDF')):
                            continue
                        
                        # Create supplier folder
                        supplier_folder = base_folder / supplier_name.replace(' ', '_')
                        supplier_folder.mkdir(parents=True, exist_ok=True)
                        
                        # Create unique filename
                        month_year = statement_date.strftime('%Y-%m')
                        unique_filename = f"{supplier_name.replace(' ', '_')}_{month_year}_{filename}"
                        filepath = supplier_folder / unique_filename
                        
                        if self.dry_run:
                            logger.info(f"[DRY RUN] Would download: {unique_filename}")
                            downloaded_files.append(str(filepath))
                        else:
                            # Save file
                            with open(filepath, 'wb') as f:
                                f.write(part.get_payload(decode=True))
                            
                            logger.info(f"Downloaded: {unique_filename}")
                            downloaded_files.append(str(filepath))
                            self.stats['pdfs_downloaded'] += 1
                
                except Exception as part_error:
                    logger.error(f"Error processing attachment in email {email_id}: {str(part_error)}")
                    continue
            
            return downloaded_files
            
        except Exception as e:
            logger.error(f"Error downloading attachments from email {email_id}: {str(e)}")
            self.stats['errors'] += 1
            return []
    
    def process_statement_file(self, file_path: str) -> bool:
        """Process a downloaded statement file"""
        try:
            if self.dry_run:
                logger.info(f"[DRY RUN] Would process: {file_path}")
                return True
            
            logger.info(f"Processing statement file: {file_path}")
            
            # Extract data using statement extractor
            extractor = StatementExtractor(
                pdf_path=file_path,
                save_to_db=True,
                save_to_excel=False,
                db_session=self.db_session
            )
            
            # Extract data
            success = extractor.extract_all_pages()
            if not success:
                logger.error(f"Failed to extract data from: {file_path}")
                self.stats['errors'] += 1
                return False
            
            # Save to database
            db_success = extractor.save_to_database()
            if not db_success:
                logger.error(f"Failed to save to database: {file_path}")
                self.stats['errors'] += 1
                return False
            
            # Upload to S3
            try:
                file_key = f"statements/{Path(file_path).name}"
                upload_file(file_path, file_key, is_invoice=False)
                logger.info(f"Uploaded to S3: {file_key}")
            except Exception as s3_error:
                logger.warning(f"S3 upload failed for {file_path}: {str(s3_error)}")
                # Don't fail the whole process for S3 issues
            
            self.stats['statements_processed'] += 1
            self.stats['statements_saved'] += 1
            
            logger.info(f"Successfully processed: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error processing statement {file_path}: {str(e)}")
            self.stats['errors'] += 1
            return False
    
    def download_statements_for_period(self, from_months_ago: int, to_months_ago: int, 
                                     supplier_filter: Optional[List[str]] = None) -> Dict[str, Any]:
        """Main method to download statements for a period"""
        try:
            # Ensure suppliers exist in database
            self.ensure_suppliers_exist()
            
            # Generate date ranges
            date_ranges = self.generate_date_ranges(from_months_ago, to_months_ago)
            
            # Setup download directory
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            base_folder = Path(INVOICE_DOWNLOAD_FOLDER) / f"historical_statements_{timestamp}"
            
            if not self.dry_run:
                base_folder.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created download directory: {base_folder}")
            
            # Process each date range
            all_downloaded_files = []
            
            for start_date, end_date in date_ranges:
                logger.info(f"Processing period: {start_date.strftime('%Y-%m')} to {end_date.strftime('%Y-%m')}")
                
                # Search for emails in this period
                email_ids = self.search_emails_for_date_range(start_date, end_date)
                self.stats['emails_searched'] += len(email_ids)
                
                # Process each email
                for email_id in email_ids:
                    try:
                        downloaded_files = self.download_attachments_from_email(email_id, base_folder)
                        all_downloaded_files.extend(downloaded_files)
                        
                        # Small delay to be nice to the email server
                        time.sleep(0.1)
                        
                    except Exception as email_error:
                        logger.error(f"Error processing email {email_id}: {str(email_error)}")
                        self.stats['errors'] += 1
                        continue
            
            # Process downloaded files
            if not self.dry_run:
                logger.info(f"Processing {len(all_downloaded_files)} downloaded files...")
                
                for file_path in all_downloaded_files:
                    try:
                        # Apply supplier filter if specified
                        if supplier_filter:
                            file_supplier = None
                            for supplier in supplier_filter:
                                if supplier.replace(' ', '_') in file_path:
                                    file_supplier = supplier
                                    break
                            
                            if not file_supplier:
                                logger.info(f"Skipping {file_path} - not in supplier filter")
                                continue
                        
                        self.process_statement_file(file_path)
                        
                    except Exception as process_error:
                        logger.error(f"Error processing file {file_path}: {str(process_error)}")
                        self.stats['errors'] += 1
                        continue
                
                # Clean up temporary files
                try:
                    import shutil
                    shutil.rmtree(base_folder)
                    logger.info(f"Cleaned up temporary directory: {base_folder}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to clean up {base_folder}: {str(cleanup_error)}")
            
            # Return results
            return {
                'success': True,
                'statistics': self.stats,
                'period': f"{from_months_ago} to {to_months_ago} months ago",
                'files_processed': len(all_downloaded_files)
            }
            
        except Exception as e:
            logger.error(f"Error in download_statements_for_period: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'statistics': self.stats
            }
    
    def print_summary(self):
        """Print a summary of the operation"""
        print("\n" + "="*60)
        print("STATEMENT DOWNLOAD SUMMARY")
        print("="*60)
        print(f"Emails searched:       {self.stats['emails_searched']:,}")
        print(f"Emails found:          {self.stats['emails_found']:,}")
        print(f"PDFs downloaded:       {self.stats['pdfs_downloaded']:,}")
        print(f"Statements processed:  {self.stats['statements_processed']:,}")
        print(f"Statements saved:      {self.stats['statements_saved']:,}")
        print(f"Skipped existing:      {self.stats['skipped_existing']:,}")
        print(f"Errors:                {self.stats['errors']:,}")
        print("="*60)


def main():
    """Main function with command line argument parsing"""
    parser = argparse.ArgumentParser(
        description="Download and process monthly statements for the last year",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download statements from the last 12 months
  python scripts/download_last_year_statements.py
  
  # Download statements from 6 months ago to now
  python scripts/download_last_year_statements.py --from-months-ago 6
  
  # Download only specific suppliers
  python scripts/download_last_year_statements.py --suppliers "BMW Plumbing Supplies,Y & S Plumbing Supply"
  
  # Dry run to see what would be processed
  python scripts/download_last_year_statements.py --dry-run
  
  # Force reprocess existing statements
  python scripts/download_last_year_statements.py --force
        """
    )
    
    parser.add_argument(
        '--from-months-ago', 
        type=int, 
        default=12,
        help='Number of months ago to start from (default: 12)'
    )
    
    parser.add_argument(
        '--to-months-ago', 
        type=int, 
        default=0,
        help='Number of months ago to end at (default: 0, meaning current month)'
    )
    
    parser.add_argument(
        '--suppliers', 
        type=str,
        help='Comma-separated list of suppliers to process (default: all)'
    )
    
    parser.add_argument(
        '--dry-run', 
        action='store_true',
        help='Preview what would be processed without downloading'
    )
    
    parser.add_argument(
        '--force', 
        action='store_true',
        help='Reprocess existing statements'
    )
    
    parser.add_argument(
        '--verbose', 
        action='store_true',
        help='Enable detailed logging'
    )
    
    args = parser.parse_args()
    
    # Parse supplier filter
    supplier_filter = None
    if args.suppliers:
        supplier_filter = [s.strip() for s in args.suppliers.split(',')]
        print(f"Filtering for suppliers: {supplier_filter}")
    
    # Validate arguments
    if args.from_months_ago < args.to_months_ago:
        print("Error: --from-months-ago must be >= --to-months-ago")
        sys.exit(1)
    
    # Show what will be processed
    print(f"Processing statements from {args.from_months_ago} months ago to {args.to_months_ago} months ago")
    if args.dry_run:
        print("DRY RUN MODE - No files will be downloaded or processed")
    if args.force:
        print("FORCE MODE - Existing statements will be reprocessed")
    
    # Run the downloader
    try:
        with StatementDownloader(
            dry_run=args.dry_run, 
            force=args.force, 
            verbose=args.verbose
        ) as downloader:
            
            result = downloader.download_statements_for_period(
                from_months_ago=args.from_months_ago,
                to_months_ago=args.to_months_ago,
                supplier_filter=supplier_filter
            )
            
            downloader.print_summary()
            
            if result['success']:
                print(f"\n✅ Successfully completed! Processed {result['files_processed']} files.")
                sys.exit(0)
            else:
                print(f"\n❌ Failed: {result['error']}")
                sys.exit(1)
                
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")
        logger.exception("Unexpected error in main")
        sys.exit(1)


if __name__ == "__main__":
    main() 